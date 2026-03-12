"""Foundry Local client – wraps the OpenAI-compatible endpoint."""

from __future__ import annotations

import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, List, Optional

import openai

from src.config import Config


class FoundryClient:
    """Thin wrapper around the Foundry Local OpenAI-compatible API."""

    def __init__(self, config: Config) -> None:
        self._cfg = config
        self._model_id: str = ""
        self._model_alias: str = config.foundry_model_alias
        self._client: Optional[openai.OpenAI] = None
        self._manager: Any = None  # FoundryLocalManager instance
        self._initialised = False
        self._catalog_cache: Optional[List[Dict[str, Any]]] = None
        self._catalog_cache_time: float = 0
        self._catalog_ttl: float = 30.0  # cache TTL in seconds

    # ── lifecycle ────────────────────────────────────────────────────

    def initialise(self) -> bool:
        """Connect to Foundry Local (SDK discovery preferred, env fallback)."""
        try:
            return self._init_via_sdk()
        except Exception as exc:
            print(f"[foundry] SDK init failed ({exc}), trying env/fallback…")
            return self._init_via_env()

    def _init_via_sdk(self) -> bool:
        from foundry_local import FoundryLocalManager

        print("[foundry] starting Foundry Local manager …")
        manager = FoundryLocalManager(self._cfg.foundry_model_alias)
        self._manager = manager
        model_info = manager.get_model_info(self._cfg.foundry_model_alias)
        if model_info is None:
            raise RuntimeError(
                f"model '{self._cfg.foundry_model_alias}' not found in catalog"
            )
        self._model_id = model_info.id
        self._model_alias = model_info.alias
        self._client = openai.OpenAI(
            base_url=manager.endpoint,
            api_key=manager.api_key,
        )
        self._initialised = True
        print(f"[foundry] connected via SDK – model: {self._model_id}")
        return True

    def _init_via_env(self) -> bool:
        base = self._cfg.foundry_base_url
        if not base:
            print(
                "[foundry] ERROR: Foundry Local SDK not available and "
                "FOUNDRY_LOCAL_BASE_URL not set.\n"
                "  → Install SDK: pip install foundry-local-sdk\n"
                "  → Or set FOUNDRY_LOCAL_BASE_URL=http://127.0.0.1:<port>/v1"
            )
            return False
        self._model_id = self._cfg.foundry_model_alias
        self._client = openai.OpenAI(
            base_url=base if base.endswith("/v1") else base + "/v1",
            api_key=self._cfg.api_key,
        )
        self._initialised = True
        print(f"[foundry] connected via env URL – model alias: {self._model_id}")
        return True

    def _ensure_manager(self) -> Any:
        """Return the SDK manager, creating a lightweight one if needed."""
        if self._manager is not None:
            return self._manager
        try:
            from foundry_local import FoundryLocalManager
            self._manager = FoundryLocalManager(bootstrap=False)
            print("[foundry] created lightweight catalog manager")
        except Exception as exc:
            print(f"[foundry] cannot create catalog manager: {exc}")
        return self._manager

    # ── chat completions ─────────────────────────────────────────────

    def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> Optional[str]:
        """Send a chat completion request and return the assistant reply."""
        if not self._initialised or self._client is None:
            print("[foundry] client not initialised")
            return None
        tok = max_tokens or self._cfg.max_completion_tokens
        try:
            kwargs: Dict[str, Any] = {
                "model": self._model_id,
                "messages": messages,
                "temperature": temperature or self._cfg.temperature,
                "stream": True,
            }
            kwargs["max_completion_tokens"] = tok

            resp = self._client.chat.completions.create(**kwargs)
            # Streaming: collect chunks for faster first-token
            chunks: list[str] = []
            for chunk in resp:
                delta = chunk.choices[0].delta if chunk.choices else None
                if delta and delta.content:
                    chunks.append(delta.content)
            return "".join(chunks) if chunks else None
        except openai.APIConnectionError:
            print(
                "[foundry] cannot reach Foundry Local – is the service running?\n"
                "  → Run: foundry model run " + self._cfg.foundry_model_alias
            )
            return None
        except Exception as exc:
            # Some endpoints don't support max_completion_tokens or streaming
            if "max_completion_tokens" in str(exc) or "stream" in str(exc).lower():
                try:
                    fallback: Dict[str, Any] = {
                        "model": self._model_id,
                        "messages": messages,
                        "temperature": temperature or self._cfg.temperature,
                        "stream": False,
                        "max_tokens": tok,
                    }
                    resp = self._client.chat.completions.create(**fallback)
                    return resp.choices[0].message.content
                except Exception as inner:
                    print(f"[foundry] chat error (retry): {inner}")
                    return None
            print(f"[foundry] chat error: {exc}")
            return None

    # ── utilities ────────────────────────────────────────────────────

    def list_models(self) -> List[str]:
        """List models available on the running Foundry Local instance."""
        if not self._initialised or self._client is None:
            return []
        try:
            models = self._client.models.list()
            return [m.id for m in models.data]
        except Exception:
            return []

    @property
    def model_id(self) -> str:
        return self._model_id

    @property
    def model_alias(self) -> str:
        return self._model_alias

    # ── model management ─────────────────────────────────────────────

    def get_catalog_models(self) -> List[Dict[str, Any]]:
        """Return catalog models with their download/load status."""
        # Serve from cache if still fresh
        now = time.monotonic()
        if self._catalog_cache is not None and (now - self._catalog_cache_time) < self._catalog_ttl:
            return self._catalog_cache

        manager = self._ensure_manager()
        if manager is None:
            return self._catalog_cache or []
        try:
            # Parallel fetch – ~1.4s vs ~1.7s sequential
            with ThreadPoolExecutor(max_workers=3) as pool:
                f_cat = pool.submit(manager.list_catalog_models)
                f_cached = pool.submit(manager.list_cached_models)
                f_loaded = pool.submit(manager.list_loaded_models)
                catalog = f_cat.result(timeout=30)
                cached_ids = {m.id for m in f_cached.result(timeout=30)}
                loaded_ids = {m.id for m in f_loaded.result(timeout=30)}

            # Group by alias – pick the best variant per alias
            seen_aliases: Dict[str, Dict[str, Any]] = {}
            for m in catalog:
                alias = m.alias
                if alias in seen_aliases:
                    continue
                status = "available"
                if m.id in loaded_ids:
                    status = "loaded"
                elif m.id in cached_ids:
                    status = "cached"
                seen_aliases[alias] = {
                    "alias": alias,
                    "id": m.id,
                    "size_mb": m.file_size_mb,
                    "status": status,
                    "publisher": getattr(m, "publisher", ""),
                    "supports_tool_calling": getattr(m, "supports_tool_calling", False),
                }
            # Mark the current model
            for entry in seen_aliases.values():
                entry["current"] = entry["alias"] == self._model_alias
            result = sorted(seen_aliases.values(), key=lambda x: x["alias"])

            # Update cache
            self._catalog_cache = result
            self._catalog_cache_time = time.monotonic()
            return result
        except Exception as exc:
            print(f"[foundry] error listing models: {exc}")
            return self._catalog_cache or []

    def switch_model(
        self,
        alias: str,
        progress_cb: Optional[Callable[[str, str, Optional[int]], None]] = None,
    ) -> bool:
        """Switch to a different model. Downloads if needed.

        progress_cb(alias, status, percent) is called with status updates:
          "checking", "downloading", "loading", "ready", "error"
        """
        manager = self._ensure_manager()
        if manager is None:
            return False
        try:
            if progress_cb:
                progress_cb(alias, "checking", None)

            # Check if model needs downloading
            cached_ids = {m.id for m in manager.list_cached_models()}
            model_info = manager.get_model_info(alias)
            if model_info is None:
                if progress_cb:
                    progress_cb(alias, "error", None)
                return False

            if model_info.id not in cached_ids:
                if progress_cb:
                    progress_cb(alias, "downloading", None)
                print(f"[foundry] downloading model {alias} …")
                manager.download_model(alias)
                print(f"[foundry] download complete: {alias}")

            if progress_cb:
                progress_cb(alias, "loading", None)

            manager.load_model(alias, ttl=3600)
            self._model_id = manager.get_model_info(alias).id
            self._model_alias = alias
            self._catalog_cache = None  # invalidate on model switch
            print(f"[foundry] switched to model: {self._model_id}")

            if progress_cb:
                progress_cb(alias, "ready", 100)
            return True
        except Exception as exc:
            print(f"[foundry] model switch error: {exc}")
            if progress_cb:
                progress_cb(alias, "error", None)
            return False
