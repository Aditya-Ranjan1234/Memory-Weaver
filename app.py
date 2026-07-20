"""Vercel and local entry point for Memory Weaver."""

from memory_weaver.app import app

__all__ = ["app"]


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app:app", host="127.0.0.1", port=8000, reload=False)
