import 'dotenv/config';
import express from 'express';
import cors from 'cors';
import helmet from 'helmet';
import Database from 'better-sqlite3';
import { customAlphabet } from 'nanoid';

const app = express();
app.use(helmet());
app.use(cors());
app.use(express.json());

const PORT = process.env.PORT || 8080;
const ADMIN_TOKEN = process.env.ADMIN_TOKEN || 'dev-admin';
const DB_PATH = process.env.DATABASE_PATH || './data/licenses.db';

const db = new Database(DB_PATH);

db.exec(`
  CREATE TABLE IF NOT EXISTS licenses (
    key TEXT PRIMARY KEY,
    plan TEXT NOT NULL CHECK(plan IN ('day','week','month','lifetime')),
    created_at INTEGER NOT NULL,
    expires_at INTEGER,
    max_activations INTEGER NOT NULL DEFAULT 1,
    activations INTEGER NOT NULL DEFAULT 0,
    banned INTEGER NOT NULL DEFAULT 0
  );
  CREATE TABLE IF NOT EXISTS activations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT NOT NULL,
    hwid TEXT NOT NULL,
    first_seen_at INTEGER NOT NULL,
    last_seen_at INTEGER NOT NULL,
    FOREIGN KEY(key) REFERENCES licenses(key)
  );
`);

const nanoid = customAlphabet('ABCDEFGHJKLMNPQRSTUVWXYZ23456789', 20);

function planToMs(plan) {
  switch (plan) {
    case 'day': return 24 * 60 * 60 * 1000;
    case 'week': return 7 * 24 * 60 * 60 * 1000;
    case 'month': return 30 * 24 * 60 * 60 * 1000;
    case 'lifetime': return null;
    default: throw new Error('unknown plan');
  }
}

function requireAdmin(req, res, next) {
  const token = req.header('x-admin-token');
  if (!token || token !== ADMIN_TOKEN) {
    return res.status(401).json({ error: 'unauthorized' });
  }
  next();
}

// Health
app.get('/health', (_req, res) => res.json({ ok: true }));

// Generate license keys (admin)
app.post('/admin/generate', requireAdmin, (req, res) => {
  const { plan, quantity = 1 } = req.body || {};
  if (!['day','week','month','lifetime'].includes(plan)) {
    return res.status(400).json({ error: 'invalid plan' });
  }
  const now = Date.now();
  const duration = planToMs(plan);
  const expiresAt = duration == null ? null : now + duration;

  const insert = db.prepare(`INSERT INTO licenses (key, plan, created_at, expires_at) VALUES (?, ?, ?, ?)`);
  const keys = [];
  const tx = db.transaction(() => {
    for (let i = 0; i < quantity; i++) {
      const k = nanoid();
      insert.run(k, plan, now, expiresAt);
      keys.push(k);
    }
  });
  tx();
  res.json({ plan, quantity, keys });
});

// Verify/bind
app.post('/auth/verify', (req, res) => {
  const { key, hwid } = req.body || {};
  if (!key || !hwid) return res.status(400).json({ error: 'missing key or hwid' });

  const lic = db.prepare('SELECT * FROM licenses WHERE key = ?').get(key);
  if (!lic) return res.status(404).json({ error: 'not_found' });
  if (lic.banned) return res.status(403).json({ error: 'banned' });
  if (lic.expires_at && Date.now() > lic.expires_at) return res.status(403).json({ error: 'expired' });

  const existing = db.prepare('SELECT * FROM activations WHERE key = ? AND hwid = ?').get(key, hwid);
  if (existing) {
    db.prepare('UPDATE activations SET last_seen_at = ? WHERE id = ?').run(Date.now(), existing.id);
    return res.json({ ok: true, plan: lic.plan, expires_at: lic.expires_at });
  }

  const count = db.prepare('SELECT COUNT(*) as c FROM activations WHERE key = ?').get(key).c;
  if (count >= lic.max_activations) {
    return res.status(403).json({ error: 'activation_limit' });
  }

  const now = Date.now();
  db.prepare('INSERT INTO activations (key, hwid, first_seen_at, last_seen_at) VALUES (?, ?, ?, ?)')
    .run(key, hwid, now, now);
  db.prepare('UPDATE licenses SET activations = activations + 1 WHERE key = ?').run(key);
  return res.json({ ok: true, plan: lic.plan, expires_at: lic.expires_at });
});

// Admin: revoke/ban
app.post('/admin/ban', requireAdmin, (req, res) => {
  const { key, banned } = req.body || {};
  if (!key) return res.status(400).json({ error: 'missing key' });
  db.prepare('UPDATE licenses SET banned = ? WHERE key = ?').run(banned ? 1 : 0, key);
  res.json({ ok: true });
});

app.listen(PORT, () => {
  console.log(`License server listening on :${PORT}`);
});
