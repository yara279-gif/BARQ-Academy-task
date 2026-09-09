# Application contract

The supplied Flask API uses real PostgreSQL and Redis. Keep this behavior.

- GET /: 200, message and instance_id.
- GET /health: 200 while the app process can respond. No dependency check.
- GET /ready: 200 only when PostgreSQL and Redis respond; otherwise 503.
- GET /instance: 200, distinct instance_id, also returned in X-Instance-ID.
- POST /records: store a PostgreSQL record; JSON body {"title":"Video proof"}, return 201.
- GET /records: list persisted records as {"records":[{"id":1,"title":"..."}], ...}.
- GET /counter: atomically increment the shared Redis counter and return its value.
- Every response includes a request ID. Unknown routes return 404.
- Invalid record titles return 400. Use a non-empty string of at most 200 characters.
- Dependency failures return 503 without replacing real SQL/Redis behavior with mock data.

Example requests after repair:

```bash
curl -i http://127.0.0.1:8080/health
curl -i http://127.0.0.1:8080/ready
curl -H 'Content-Type: application/json' -d '{"title":"Persistence proof"}' http://127.0.0.1:8080/records
curl http://127.0.0.1:8080/records
curl http://127.0.0.1:8080/counter
curl http://127.0.0.1:8080/instance
```

Environment inputs: INSTANCE_ID, APP_MESSAGE, APP_HOST, APP_PORT, DATABASE_URL and REDIS_URL.
The app listens on APP_HOST:APP_PORT. PostgreSQL initializes database/init.sql on fresh storage.
The assessment is about deployment/operations; extend app-only tests as needed, but do not
change endpoint semantics to bypass dependencies. These tests do not prove environment health.

The three historical logs are a separate training incident, not a complete list of current faults.
