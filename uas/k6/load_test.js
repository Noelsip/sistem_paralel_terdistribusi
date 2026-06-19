// k6 load test untuk Pub-Sub Log Aggregator.
import http from 'k6/http';
import { check, sleep } from 'k6';
import { uuidv4 } from 'https://jslib.k6.io/k6-utils/1.4.0/index.js';

const BASE_URL = __ENV.BASE_URL || 'http://localhost:8090';
const TOPIC = `k6.${__ENV.RUN_ID || 'run'}`;

export const options = {
  scenarios: {
    publish_load: {
      executor: 'ramping-vus',
      startVUs: 5,
      stages: [
        { duration: '15s', target: 30 },
        { duration: '30s', target: 30 },
        { duration: '10s', target: 0 },
      ],
    },
  },
  thresholds: {
    http_req_failed: ['rate<0.01'],
    http_req_duration: ['p(95)<800'],
  },
};

// Pool event_id global agar VU dapat mengirim duplikat (event_id sama).
const POOL_SIZE = 2000;
const pool = [];
for (let i = 0; i < POOL_SIZE; i++) pool.push(uuidv4());

export default function () {
  const dup = Math.random() < 0.3; 
  const eventId = dup ? pool[Math.floor(Math.random() * POOL_SIZE)] : uuidv4();

  const batch = [];
  for (let i = 0; i < 20; i++) {
    const isDup = Math.random() < 0.3;
    batch.push({
      topic: TOPIC,
      event_id: isDup ? pool[Math.floor(Math.random() * POOL_SIZE)] : uuidv4(),
      timestamp: new Date().toISOString(),
      source: `k6-vu-${__VU}`,
      payload: { iter: __ITER, vu: __VU },
    });
  }

  const res = http.post(`${BASE_URL}/publish`, JSON.stringify(batch), {
    headers: { 'Content-Type': 'application/json' },
  });
  check(res, { 'publish 200': (r) => r.status === 200 });
  sleep(0.1);
}

export function teardown() {
  const res = http.get(`${BASE_URL}/stats`);
  console.log('STATS akhir: ' + res.body);
}
