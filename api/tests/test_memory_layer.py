import sys
import types
from types import SimpleNamespace

if "openai" not in sys.modules:
    openai_mod = types.ModuleType("openai")

    class _OpenAI:
        def __init__(self, *args, **kwargs):
            pass

    openai_mod.OpenAI = _OpenAI
    sys.modules["openai"] = openai_mod

import storage.memory_store as memory_store
import services.memory_service as memory_service


class _StubEmbeddings:
    def create(self, model, input):
        text = str(input or "")
        val = 1.0 if ("apple" in text or "cloud" in text) else 0.0
        return SimpleNamespace(data=[SimpleNamespace(embedding=[val, 0.0, 0.0])])


class _StubClient:
    def __init__(self):
        self.embeddings = _StubEmbeddings()


def test_memory_store_roundtrip(tmp_path, monkeypatch):
    store_path = tmp_path / "memory.json"
    monkeypatch.setattr(memory_store, "MEMORY_STORE_PATH", str(store_path))

    assert memory_store.load_memory("u1") == [], "expected empty store for new user"

    entry = {"id": "1", "content": "hello"}
    memory_store.append_memory("u1", entry)
    assert memory_store.load_memory("u1") == [entry], "append_memory should persist entry"

    memory_store.save_memory("u1", [entry, {"id": "2", "content": "bye"}])
    out = memory_store.load_memory("u1")
    assert len(out) == 2, "save_memory should persist all entries"


def test_memory_service_write_and_search(tmp_path, monkeypatch):
    store_path = tmp_path / "memory.json"
    monkeypatch.setattr(memory_store, "MEMORY_STORE_PATH", str(store_path))
    monkeypatch.setattr(memory_service, "client", _StubClient())

    calls = {"sync": 0}

    def _fake_save(user_id, entries):
        calls["sync"] += 1
        return True

    monkeypatch.setattr(memory_service, "save_memory_to_supabase", _fake_save)

    entry = memory_service.write_memory(
        user_id="u1",
        content="apple",
        tags=["fruit"],
        source="test",
        sync=True,
    )
    assert entry["content"] == "apple", "write_memory should return stored content"
    assert calls["sync"] == 1, "expected Supabase sync when sync=True"

    results = memory_service.search_memory("u1", "apple", limit=5)
    assert results, "expected search_memory to return results"
    assert results[0]["content"] == "apple", "expected apple memory to rank first"


def test_memory_service_loads_from_supabase_when_local_empty(tmp_path, monkeypatch):
    store_path = tmp_path / "memory.json"
    monkeypatch.setattr(memory_store, "MEMORY_STORE_PATH", str(store_path))
    monkeypatch.setattr(memory_service, "client", _StubClient())

    supa_entries = [
        {
            "id": "s1",
            "content": "from cloud",
            "tags": [],
            "created_at": "2024-01-01T00:00:00Z",
        }
    ]

    monkeypatch.setattr(memory_service, "load_memory", lambda user_id: [])
    monkeypatch.setattr(memory_service, "load_memory_from_supabase", lambda user_id: supa_entries)

    saved = {"called": False}

    def _fake_save(user_id, entries):
        saved["called"] = True

    monkeypatch.setattr(memory_service, "save_memory", _fake_save)

    results = memory_service.search_memory("u1", "cloud", limit=3)
    assert saved["called"], "expected Supabase memory to be cached locally"
    assert results, "expected search to return Supabase-backed entries"
