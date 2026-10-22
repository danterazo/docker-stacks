import assert from "node:assert/strict";
import test from "node:test";
import {
	checkRecord,
	difficulty,
	discordDestination,
	formatDifficulty,
	formatRecordMessage,
	readBest,
	recordDetails,
	sendRecordNotification,
} from "./best-difficulty.mjs";

function fixture(initial = {}) {
	const state = structuredClone(initial);
	const notifications = [];
	const heartbeats = [];
	const miner = { name: "Antminer-S19K-Pro-Slim-A" };
	return {
		state,
		notifications,
		heartbeats,
		async check(value, overrides = {}) {
			return checkRecord({
				miner,
				state,
				persist: async () => {},
				summary: async () => ({ STATUS: [{ STATUS: "S" }], SUMMARY: [{ "Best Share": value }] }),
				notify: async (...args) => notifications.push(args),
				push: async (...args) => heartbeats.push(args),
				...overrides,
			});
		},
	};
}

test("initial observation establishes a silent baseline", async () => {
	const subject = fixture();
	await subject.check(100);
	assert.equal(subject.notifications.length, 0);
	assert.equal(subject.state["Antminer-S19K-Pro-Slim-A"].highest, "100");
	assert.equal(subject.heartbeats.length, 1);
});

test("only strictly higher records notify; lower values never reset the baseline", async () => {
	const subject = fixture();
	for (const value of [100, 100, 90, 110, 110, 20, 105, 120]) {
		await subject.check(value);
	}
	assert.deepEqual(
		subject.notifications.map((args) => args.slice(1, 3)),
		[
			["100", "110"],
			["110", "120"],
		],
	);
});

test("persisted baseline survives a restart without a duplicate announcement", async () => {
	const subject = fixture({ "Antminer-S19K-Pro-Slim-A": { highest: "200", notified: "200" } });
	await subject.check(200);
	await subject.check(150);
	assert.equal(subject.notifications.length, 0);
});

test("failed delivery remains pending and retries even if miner reports a lower value", async () => {
	const subject = fixture();
	await subject.check(100);
	await assert.rejects(
		subject.check(150, {
			notify: async () => {
				throw new Error("offline");
			},
		}),
	);
	assert.deepEqual(subject.state["Antminer-S19K-Pro-Slim-A"], { highest: "150", notified: "100", details: {} });
	await subject.check(10);
	assert.equal(subject.notifications.length, 1);
	assert.equal(subject.state["Antminer-S19K-Pro-Slim-A"].notified, "150");
});

test("API failure does not create a baseline, notification or heartbeat", async () => {
	const subject = fixture();
	await assert.rejects(
		subject.check(100, {
			summary: async () => {
				throw new Error("unreachable");
			},
		}),
	);
	assert.deepEqual(subject.state, {});
	assert.equal(subject.notifications.length, 0);
	assert.equal(subject.heartbeats.length, 0);
	assert.throws(() => readBest({ STATUS: [{ STATUS: "E" }] }));
	assert.throws(() => readBest({ STATUS: [{ STATUS: "S" }], SUMMARY: [{}] }));
});

test("invalid and imprecise numbers are rejected; integer strings retain precision", () => {
	for (const value of [null, undefined, true, -1, 0.1, Number.MAX_SAFE_INTEGER + 1, "1e10"]) {
		assert.throws(() => difficulty(value));
	}
	assert.equal(difficulty("12345678901234567890"), 12345678901234567890n);
});

test("state is persisted before Discord delivery", async () => {
	const subject = fixture();
	await subject.check(100);
	const order = [];
	await subject.check(110, {
		persist: async () => order.push("persist"),
		notify: async () => order.push("notify"),
	});
	assert.deepEqual(order, ["persist", "notify", "persist"]);
});

test("failed state writes do not advance the in-memory baseline or send records", async () => {
	const subject = fixture();
	const persist = async () => {
		throw new Error("disk full");
	};
	await assert.rejects(subject.check(100, { persist }));
	assert.deepEqual(subject.state, {});
	await subject.check(100);
	await assert.rejects(subject.check(150, { persist }));
	assert.equal(subject.state["Antminer-S19K-Pro-Slim-A"].highest, "100");
	assert.equal(subject.notifications.length, 0);
	await subject.check(150);
	assert.equal(subject.notifications.length, 1);
});

test("difficulty formatting uses mining units without confusing G and T", () => {
	assert.equal(formatDifficulty("6230000000"), "6.23G");
	assert.equal(formatDifficulty(526000000000), "526G");
	assert.equal(formatDifficulty(123456000000000), "123.46T");
	assert.equal(formatDifficulty(0), "0");
	assert.equal(formatDifficulty(undefined), "Unavailable");
	assert.equal(formatDifficulty(NaN), "Unavailable");
});

test("record messages match the reference layout with aligned identity fields", () => {
	const miner = { name: "Antminer-S19K-Pro-Slim-A", url: "http://192.168.60.10:8080/api" };
	const content = formatRecordMessage(miner, "1000000", "6230000000", {
		hostname: "Antminer-S19K-Pro-Slim-A",
		mac: "00:11:22:33:44:55",
		coin: "BCH",
		networkDifficulty: 526000000000,
	});
	assert.match(content, /New best difficulty found!/);
	assert.match(content, /Diff: \*\*6\.23G\*\* \(BCH Network: 526G\)/);
	assert.ok(content.includes("Hostname: Antminer-S19K-Pro-Slim-A\nIP:       192.168.60.10\nMAC:      00:11:22:33:44:55\nCoin:     BCH\n"));
	assert.ok(content.includes("Previous: 1M"));
});

test("unknown coin and network are not guessed and metadata cannot break the code block", () => {
	const miner = { name: "Miner", url: "http://192.168.60.20:8080/api" };
	const content = formatRecordMessage(miner, "100", "200", { hostname: "bad```\nhost" });
	assert.doesNotMatch(content, /\(network: Unavailable\)/);
	assert.match(content, /Coin:\s+Unknown/);
	assert.doesNotMatch(content, /Coin:\s+(BTC|BCH)/);
	assert.match(content, /BTC Network:\s+Unavailable/);
	assert.match(content, /BCH Network:\s+Unavailable/);
	assert.equal(content.match(/```/g).length, 2);
});

test("record coin follows matching per-pool best, not preferred or active pool", () => {
	const pools = {
		STATUS: [{ STATUS: "S" }],
		POOLS: [
			{ URL: "stratum+tcp://btc.samskeyti.net:3333", "Best Share": 50, "Stratum Active": true, Priority: 0 },
			{ URL: "stratum+tcp://bch.samskeyti.net:3333", "Best Share": 200, "Stratum Active": true, Priority: 2 },
		],
	};
	const mapping = { "btc.samskeyti.net": "BTC", "bch.samskeyti.net": "BCH" };
	const networks = { BTC: { difficulty: 1000 }, BCH: { difficulty: 500 } };
	const details = recordDetails("200", undefined, pools, mapping, networks, "now");
	assert.equal(details.coin, "BCH");
	assert.equal(details.poolHost, "bch.samskeyti.net");
	assert.equal(details.networkDifficulty, 500);
	assert.equal(recordDetails("999", undefined, pools, mapping, networks, "now").coin, undefined);
	pools.POOLS[0]["Best Share"] = 200;
	assert.equal(recordDetails("200", undefined, pools, mapping, networks, "now").coin, undefined);
});

test("unknown pool hosts and failed pool responses cannot acquire a guessed coin", () => {
	const pools = { STATUS: [{ STATUS: "S" }], POOLS: [{ URL: "stratum+tcp://unknown.example:3333", "Best Share": 200 }] };
	assert.equal(recordDetails("200", undefined, pools, {}, {}, "now").coin, undefined);
	pools.STATUS[0].STATUS = "E";
	assert.equal(recordDetails("200", undefined, pools, { "unknown.example": "BTC" }, {}, "now").coin, undefined);
});

test("a delivery retry preserves the record-time metadata instead of using a new pool", async () => {
	const subject = fixture();
	await subject.check(100);
	const details = { coin: "BTC", networkDifficulty: 123, networkTime: "original observation" };
	await assert.rejects(
		subject.check(200, {
			describe: async () => details,
			notify: async () => {
				throw new Error("offline");
			},
		}),
	);
	await subject.check(150, {
		describe: async () => {
			throw new Error("must not run");
		},
	});
	assert.deepEqual(subject.notifications[0][3], details);
});

test("optional metadata failure does not prevent record delivery", async () => {
	const subject = fixture();
	await subject.check(100);
	await subject.check(200, {
		describe: async () => {
			throw new Error("metadata unavailable");
		},
	});
	assert.equal(subject.notifications.length, 1);
	assert.deepEqual(subject.notifications[0][3], {});
});

test("compact miner display names do not rename persistent record keys", async () => {
	const miner = { name: "Antminer-S19K-Pro-Slim-A", displayName: "S19K Pro Slim A", url: "http://192.168.60.10:8080/api" };
	const content = formatRecordMessage(miner, "100", "200");
	assert.match(content, /Miner:\s+S19K Pro Slim A/);
	const state = {};
	await checkRecord({
		miner,
		state,
		persist: async () => {},
		summary: async () => ({ STATUS: [{ STATUS: "S" }], SUMMARY: [{ "Best Share": 200 }] }),
		notify: async () => {},
		push: async () => {},
	});
	assert.deepEqual(Object.keys(state), ["Antminer-S19K-Pro-Slim-A"]);
});

test("known network difficulties remain visible when the record coin is unknown", () => {
	const miner = { name: "Miner", url: "http://192.168.60.10:8080/api" };
	const content = formatRecordMessage(miner, "100", "200", {
		networks: { BTC: { difficulty: 1000000000000 }, BCH: { difficulty: 500000000000 } },
	});
	assert.match(content, /BTC Network:\s+1T/);
	assert.match(content, /BCH Network:\s+500G/);
	assert.match(content, /Coin:\s+Unknown/);
	assert.doesNotMatch(content, /Network:[^\n]*Unavailable/);
	assert.doesNotMatch(content, /\(network:/);
});

test("attributed record uses coin-first network label and per-coin lookup", () => {
	const miner = { name: "Miner", url: "http://192.168.60.10:8080/api" };
	const content = formatRecordMessage(miner, "100", "200", {
		coin: "BTC",
		networks: { BTC: { difficulty: 1000000000000 } },
	});
	assert.match(content, /\(BTC Network: 1T\)/);
	assert.doesNotMatch(content, /network: 1T BTC/);
});

test("each miner sends only to its own webhook and preserves Discord's configured identity", async () => {
	const environment = {
		LUXOS_DISCORD_WEBHOOK_A: "https://discord.com/api/webhooks/111/example-a",
		LUXOS_DISCORD_WEBHOOK_B: "https://discord.com/api/webhooks/222/example-b",
	};
	const calls = [];
	const send = async (url, options) => calls.push({ url: String(url), payload: JSON.parse(options.body) });
	for (const suffix of ["A", "B"]) {
		const miner = { name: `Miner ${suffix}`, url: "http://192.168.60.10:8080/api", discordWebhookEnv: `LUXOS_DISCORD_WEBHOOK_${suffix}` };
		await sendRecordNotification(miner, "100", "200", {}, { environment, send });
	}
	assert.equal(new URL(calls[0].url).pathname, "/api/webhooks/111/example-a");
	assert.equal(new URL(calls[1].url).pathname, "/api/webhooks/222/example-b");
	for (const call of calls) {
		assert.equal(new URL(call.url).searchParams.get("wait"), "true");
		assert.equal(Object.hasOwn(call.payload, "username"), false);
		assert.equal(Object.hasOwn(call.payload, "avatar_url"), false);
		assert.deepEqual(call.payload.allowed_mentions, { parse: [] });
	}
});

test("missing per-miner webhook cannot fall back to the old shared webhook", () => {
	const miner = { name: "Miner B", discordWebhookEnv: "LUXOS_DISCORD_WEBHOOK_B" };
	const environment = { LUXOS_DISCORD_WEBHOOK: "https://discord.com/api/webhooks/111/old-shared" };
	assert.throws(() => discordDestination(miner, environment), /Missing Discord webhook for Miner B/);
});

test("invalid webhook errors do not disclose credentials or accept other destinations", () => {
	const miner = { name: "Miner A", discordWebhookEnv: "LUXOS_DISCORD_WEBHOOK_A" };
	for (const value of [
		"secret-not-a-url",
		"http://discord.com/api/webhooks/111/secret",
		"https://discord.com.evil.example/api/webhooks/111/secret",
		"https://user:secret@discord.com/api/webhooks/111/secret",
	]) {
		assert.throws(
			() => discordDestination(miner, { LUXOS_DISCORD_WEBHOOK_A: value }),
			(error) => {
				assert.equal(error.message, "Invalid Discord webhook for Miner A");
				return true;
			},
		);
	}
});
