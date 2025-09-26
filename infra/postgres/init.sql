create table if not exists alerts(
  id bigserial primary key,
  fingerprint text,
  alertname text,
  labels jsonb,
  starts_at timestamptz,
  status text,
  created_at timestamptz default now()
);

create table if not exists decisions(
  id bigserial primary key,
  alert_id bigint references alerts(id),
  path text, -- 'rule' | 'ai'
  rule_id text,
  context jsonb,
  recommendation jsonb,
  latency_ms int,
  created_at timestamptz default now()
);

create table if not exists feedback(
  id bigserial primary key,
  decision_id bigint references decisions(id),
  vote boolean,
  notes text,
  created_at timestamptz default now()
);
