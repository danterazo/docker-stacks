import assert from 'node:assert/strict';
import test from 'node:test';
import { checkRecord, difficulty, readBest } from './best-difficulty.mjs';

function fixture(initial = {}) {
	const state = structuredClone(initial);
	const notifications = [];
	const heartbeats = [];
	const miner = { name: 'Antminer-S19K-Pro-Slim-A' };
	return {
		state, notifications, heartbeats,
		async check(value, overrides = {}) {
			return checkRecord({
				miner, state,
				persist: async () => {},
				summary: async () => ({ STATUS: [{ STATUS: 'S' }], SUMMARY: [{ 'Best Share': value }] }),
				notify: async (...args) => notifications.push(args),
				push: async (...args) => heartbeats.push(args),
				...overrides,
			});
		},
	};
}

test('initial observation establishes a silent baseline', async () => {
	const subject = fixture();
	await subject.check(100);
	assert.equal(subject.notifications.length, 0);
	assert.equal(subject.state['Antminer-S19K-Pro-Slim-A'].highest, '100');
	assert.equal(subject.heartbeats.length, 1);
});

test('only strictly higher records notify; lower values never reset the baseline', async () => {
	const subject = fixture();
	for (const value of [100, 100, 90, 110, 110, 20, 105, 120]) {
		await subject.check(value);
	}
	assert.deepEqual(subject.notifications.map(args => args.slice(1)), [['100', '110'], ['110', '120']]);
});

test('persisted baseline survives a restart without a duplicate announcement', async () => {
	const subject = fixture({ 'Antminer-S19K-Pro-Slim-A': { highest: '200', notified: '200' } });
	await subject.check(200);
	await subject.check(150);
	assert.equal(subject.notifications.length, 0);
});

test('failed delivery remains pending and retries even if miner reports a lower value', async () => {
	const subject = fixture();
	await subject.check(100);
	await assert.rejects(subject.check(150, { notify: async () => { throw new Error('offline'); } }));
	assert.deepEqual(subject.state['Antminer-S19K-Pro-Slim-A'], { highest: '150', notified: '100' });
	await subject.check(10);
	assert.equal(subject.notifications.length, 1);
	assert.equal(subject.state['Antminer-S19K-Pro-Slim-A'].notified, '150');
});

test('API failure does not create a baseline, notification or heartbeat', async () => {
	const subject = fixture();
	await assert.rejects(subject.check(100, { summary: async () => { throw new Error('unreachable'); } }));
	assert.deepEqual(subject.state, {});
	assert.equal(subject.notifications.length, 0);
	assert.equal(subject.heartbeats.length, 0);
	assert.throws(() => readBest({ STATUS: [{ STATUS: 'E' }] }));
	assert.throws(() => readBest({ STATUS: [{ STATUS: 'S' }], SUMMARY: [{}] }));
});

test('invalid and imprecise numbers are rejected; integer strings retain precision', () => {
	for (const value of [null, undefined, true, -1, 0.1, Number.MAX_SAFE_INTEGER + 1, '1e10']) {
		assert.throws(() => difficulty(value));
	}
	assert.equal(difficulty('12345678901234567890'), 12345678901234567890n);
});

test('state is persisted before Discord delivery', async () => {
	const subject = fixture();
	await subject.check(100);
	const order = [];
	await subject.check(110, {
		persist: async () => order.push('persist'),
		notify: async () => order.push('notify'),
	});
	assert.deepEqual(order, ['persist', 'notify', 'persist']);
});

test('failed state writes do not advance the in-memory baseline or send records', async () => {
	const subject = fixture();
	const persist = async () => { throw new Error('disk full'); };
	await assert.rejects(subject.check(100, { persist }));
	assert.deepEqual(subject.state, {});
	await subject.check(100);
	await assert.rejects(subject.check(150, { persist }));
	assert.equal(subject.state['Antminer-S19K-Pro-Slim-A'].highest, '100');
	assert.equal(subject.notifications.length, 0);
	await subject.check(150);
	assert.equal(subject.notifications.length, 1);
});
