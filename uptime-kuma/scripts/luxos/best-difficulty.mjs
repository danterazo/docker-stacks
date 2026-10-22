import { readFile, rename, writeFile } from "node:fs/promises";
import { pathToFileURL } from "node:url";
import { setTimeout } from "node:timers/promises";

export function difficulty(value) {
	if (typeof value === "number" && Number.isSafeInteger(value) && value >= 0) {
		return BigInt(value);
	}
	if (typeof value === "string" && /^\d+$/.test(value)) {
		return BigInt(value);
	}
	throw new Error("Best Share must be a nonnegative, lossless integer");
}

export function readBest(summary) {
	if (summary?.STATUS?.[0]?.STATUS !== "S") {
		throw new Error("LuxOS summary did not succeed");
	}
	return difficulty(summary.SUMMARY?.[0]?.["Best Share"]);
}

export function formatDifficulty(value) {
	const numeric = Number(value);
	if (value === null || value === undefined || value === "" || !Number.isFinite(numeric) || numeric < 0) {
		return "Unavailable";
	}
	const units = ["", "K", "M", "G", "T", "P", "E"];
	const index = numeric === 0 ? 0 : Math.min(Math.floor(Math.log10(numeric) / 3), units.length - 1);
	return `${(numeric / 1000 ** Math.max(index, 0)).toFixed(2).replace(/\.?0+$/, "")}${units[Math.max(index, 0)]}`;
}

export function formatRecordMessage(miner, previous, best, details = {}) {
	const clean = (value) =>
		String(value ?? "Unavailable")
			.replace(/[`\r\n]/g, " ")
			.slice(0, 160);
	const coin = details.coin ?? "Unknown";
	const network = formatDifficulty(details.networkDifficulty ?? details.networks?.[details.coin]?.difficulty);
	const fields = [
		["Miner", miner.displayName ?? miner.name],
		["Hostname", details.hostname ?? miner.name],
		["IP", new URL(miner.url).hostname],
		["MAC", details.mac],
		["Coin", coin],
		["Pool", details.poolHost],
		["Previous", formatDifficulty(previous)],
	];
	if (!details.coin) {
		fields.push(["BTC Network", formatDifficulty(details.networks?.BTC?.difficulty)]);
		fields.push(["BCH Network", formatDifficulty(details.networks?.BCH?.difficulty)]);
	}
	fields.push(["As of", details.networkTime]);
	const width = Math.max(...fields.map(([label]) => label.length)) + 2;
	const block = fields.map(([label, value]) => `${`${label}:`.padEnd(width)}${clean(value)}`).join("\n");
	const networkLabel = details.coin ? ` (${clean(coin)} Network: ${network})` : "";
	return `\u{1F4C8} New best difficulty found!\nDiff: **${formatDifficulty(best)}**${networkLabel}\n\`\`\`text\n${block}\n\`\`\``;
}

export function recordDetails(best, configResponse, poolsResponse, poolCoins, networks, networkTime) {
	const identity = configResponse?.STATUS?.[0]?.STATUS === "S" ? configResponse.CONFIG?.[0] : undefined;
	const pools = poolsResponse?.STATUS?.[0]?.STATUS === "S" ? (poolsResponse.POOLS ?? []) : [];
	const matching = [];
	for (const pool of pools) {
		try {
			if (difficulty(pool["Best Share"]) === difficulty(best)) {
				const hostname = new URL(pool.URL).hostname;
				matching.push({ hostname, coin: poolCoins[hostname] });
			}
		} catch {}
	}
	const coins = new Set(matching.map((pool) => pool.coin));
	const candidate = coins.size === 1 ? matching[0]?.coin : undefined;
	const coin = ["BTC", "BCH"].includes(candidate) ? candidate : undefined;
	return {
		hostname: identity?.Hostname,
		mac: /^[\da-f]{2}(?::[\da-f]{2}){5}$/i.test(identity?.MACAddr ?? "") ? identity.MACAddr : undefined,
		coin,
		poolHost: matching.length ? [...new Set(matching.map((pool) => pool.hostname))].join(", ") : undefined,
		networkDifficulty: coin ? networks[coin]?.difficulty : undefined,
		networks,
		networkTime,
	};
}

export async function checkRecord({ miner, state, persist, summary, notify, push, describe = async () => ({}) }) {
	const observed = readBest(await summary(miner));
	if (!state[miner.name]) {
		const baseline = { highest: String(observed), notified: String(observed) };
		await persist({ ...state, [miner.name]: baseline });
		state[miner.name] = baseline;
	}
	let record = state[miner.name];
	if (observed > difficulty(record.highest)) {
		let details = {};
		try {
			details = await describe(miner, String(observed));
		} catch {}
		record = { ...record, highest: String(observed), details };
		await persist({ ...state, [miner.name]: record });
		state[miner.name] = record;
	}
	if (difficulty(record.highest) > difficulty(record.notified)) {
		await notify(miner, record.notified, record.highest, record.details ?? {});
		record = { ...record, notified: record.highest };
		await persist({ ...state, [miner.name]: record });
		state[miner.name] = record;
	}
	await push(miner, record.highest, String(observed));
}

async function request(url, options = {}) {
	const response = await fetch(url, { ...options, signal: AbortSignal.timeout(10000) });
	if (!response.ok) {
		throw new Error(`HTTP ${response.status}`);
	}
	return response;
}

export function discordDestination(miner, environment = process.env) {
	const value = environment[miner.discordWebhookEnv];
	if (!value) {
		throw new Error(`Missing Discord webhook for ${miner.name}`);
	}
	let url;
	try {
		url = new URL(value);
	} catch {
		throw new Error(`Invalid Discord webhook for ${miner.name}`);
	}
	if (url.protocol !== "https:" || url.hostname !== "discord.com" || !url.pathname.startsWith("/api/webhooks/") || url.username || url.password) {
		throw new Error(`Invalid Discord webhook for ${miner.name}`);
	}
	return url;
}

export async function sendRecordNotification(miner, previous, best, details, { environment = process.env, send = request } = {}) {
	const url = discordDestination(miner, environment);
	url.searchParams.set("wait", "true");
	await send(url, {
		method: "POST",
		headers: { "Content-Type": "application/json" },
		body: JSON.stringify({
			allowed_mentions: { parse: [] },
			content: formatRecordMessage(miner, previous, best, details),
		}),
	});
}

export async function main() {
	const config = JSON.parse(await readFile(new URL("./miners.json", import.meta.url), "utf8"));
	for (const miner of config.miners) {
		discordDestination(miner);
		if (!process.env[miner.pushTokenEnv]) {
			throw new Error(`Missing Push token for ${miner.name}`);
		}
	}
	const statePath = "/records/state.json";
	let state;
	try {
		state = JSON.parse(await readFile(statePath, "utf8"));
	} catch (error) {
		if (error.code !== "ENOENT") {
			throw new Error("Cannot read record state; refusing to reset the baseline");
		}
		state = {};
	}
	for (const record of Object.values(state)) {
		difficulty(record.highest);
		difficulty(record.notified);
	}
	const persist = async (records) => {
		await writeFile(`${statePath}.tmp`, `${JSON.stringify(records, null, "\t")}\n`, { mode: 0o600 });
		await rename(`${statePath}.tmp`, statePath);
	};
	const api = async (miner, command) => {
		const response = await request(miner.url, {
			method: "POST",
			headers: { "Content-Type": "application/json" },
			body: JSON.stringify({ command }),
		});
		return response.json();
	};
	const summary = (miner) => api(miner, "summary");
	const describe = async (miner, best) => {
		const optional = async (operation) => {
			try {
				return await operation();
			} catch {
				return undefined;
			}
		};
		const network = (source) =>
			optional(async () => {
				const response = await request(source);
				const result = await response.json();
				const value = result.data?.difficulty;
				if (result.context?.code !== 200 || typeof value !== "number" || !Number.isFinite(value) || value <= 0) {
					throw new Error("Network difficulty unavailable");
				}
				return { difficulty: value, source };
			});
		const [identity, pools, btc, bch] = await Promise.all([
			optional(() => api(miner, "config")),
			optional(() => api(miner, "pools")),
			network(config.networkSources.BTC),
			network(config.networkSources.BCH),
		]);
		return recordDetails(best, identity, pools, config.poolCoins, { BTC: btc, BCH: bch }, new Date().toISOString());
	};
	const notify = async (miner, previous, best, details) => {
		await sendRecordNotification(miner, previous, best, details);
		console.log(`${miner.name}: new record ${best} delivered`);
	};
	const push = async (miner, best, observed) => {
		const token = process.env[miner.pushTokenEnv];
		const url = new URL(`/api/push/${encodeURIComponent(token)}`, config.kumaUrl);
		url.searchParams.set("status", "up");
		url.searchParams.set("msg", `All-time best difficulty: ${best}; miner currently reports: ${observed}`);
		const response = await request(url);
		if ((await response.json()).ok !== true) {
			throw new Error("Kuma did not accept the heartbeat");
		}
	};
	while (true) {
		for (const miner of config.miners) {
			try {
				await checkRecord({ miner, state, persist, summary, notify, push, describe });
			} catch {
				console.error(`${miner.name}: check or delivery failed; will retry without resetting records`);
			}
		}
		await setTimeout(60000);
	}
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
	main().catch(() => {
		console.error("Record helper startup failed; verify configuration and persisted state");
		process.exitCode = 1;
	});
}
