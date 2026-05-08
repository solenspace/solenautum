"""Background jobs scoped to the FastAPI lifespan TaskGroup.

Each loop is structured-concurrency owned (invariant 3) — the lifespan
group adopts the task at startup and cancels it on shutdown via
`CancelledError`.
"""
