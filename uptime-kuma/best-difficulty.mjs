import { readFile, rename, writeFile } from 'node:fs/promises';
import { pathToFileURL } from 'node:url';
import { setTimeout } from 'node:timers/promises';

export function difficulty(value) {
	if (typeof value === 'number' && Number.isSafeInteger(value) && value >= 0) {
		return BigInt(value);
	}
	if (typeof value === 'string' && /^\d+$/.test(value)) {
		return BigInt(value);
	}
	throw new Error('Best Share must be a nonnegative, lossless integer');
}

export function readBest(summary) {
	if (summary?.STATUS?.[0]?.STATUS !== 'S') {
		throw new Error('LuxOS summary did not succeed');
	}
	return difficulty(summary.SUMMARY?.[0]?.['Best Share']);
}

export async function checkRecord({ miner, state, persist, summary, notify, push }) {
	const observed = readBest(await summary(miner));
	if (!state[miner.name]) {
		const baseline = { highest: String(observed), notified: String(observed) };
		await persist({ ...state, [miner.name]: baseline });
		state[miner.name] = baseline;
	}
	let record = state[miner.name];
	if (observed > difficulty(record.highest)) {
		record = { ...record, highest: String(observed) };
		await persist({ ...state, [miner.name]: record });
		state[miner.name] = record;
	}
	if (difficulty(record.highest) > difficulty(record.notified)) {
		await notify(miner, record.notified, record.highest);
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

export async function main() {
	const config = JSON.parse(await readFile(new URL('./miners.json', import.meta.url), 'utf8'));
	const webhook = process.env.LUXOS_DISCORD_WEBHOOK;
	const parsedWebhook = new URL(webhook);
	if (parsedWebhook.protocol !== 'https:' || parsedWebhook.hostname !== 'discord.com'
		|| !parsedWebhook.pathname.startsWith('/api/webhooks/')) {
		throw new Error('A Discord HTTPS webhook is required');
	}
	for (const miner of config.miners) {
		if (!process.env[miner.pushTokenEnv]) {
			throw new Error(`Missing Push token for ${miner.name}`);
		}
	}
	const statePath = '/records/state.json';
	let state;
	try {
		state = JSON.parse(await readFile(statePath, 'utf8'));
	} catch (error) {
		if (error.code !== 'ENOENT') {
			throw new Error('Cannot read record state; refusing to reset the baseline');
		}
		state = {};
	}
	for (const record of Object.values(state)) {
		difficulty(record.highest);
		difficulty(record.notified);
	}
	const persist = async (records) => {
		await writeFile(`${statePath}.tmp`, `${JSON.stringify(records, null, '\t')}\n`, { mode: 0o600 });
		await rename(`${statePath}.tmp`, statePath);
	};
	const summary = async (miner) => {
		const response = await request(miner.url, {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({ command: 'summary' }),
		});
		return response.json();
	};
	const notify = async (miner, previous, best) => {
		const url = new URL(webhook);
		url.searchParams.set('wait', 'true');
		await request(url, {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({
				username: 'LuxOS',
				allowed_mentions: { parse: [] },
				content: `New all-time best difficulty\n**${miner.name}**\nPrevious: ${previous}\nNew best: **${best}**`,
			}),
		});
		console.log(`${miner.name}: new record ${best} delivered`);
	};
	const push = async (miner, best, observed) => {
		const token = process.env[miner.pushTokenEnv];
		const url = new URL(`/api/push/${encodeURIComponent(token)}`, config.kumaUrl);
		url.searchParams.set('status', 'up');
		url.searchParams.set('msg', `All-time best difficulty: ${best}; miner currently reports: ${observed}`);
		const response = await request(url);
		if ((await response.json()).ok !== true) {
			throw new Error('Kuma did not accept the heartbeat');
		}
	};
	while (true) {
		for (const miner of config.miners) {
			try {
				await checkRecord({ miner, state, persist, summary, notify, push });
			} catch {
				console.error(`${miner.name}: check or delivery failed; will retry without resetting records`);
			}
		}
		await setTimeout(60000);
	}
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
	main().catch(() => {
		console.error('Record helper startup failed; verify configuration and persisted state');
		process.exitCode = 1;
	});
}
