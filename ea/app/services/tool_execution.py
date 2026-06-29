from __future__ import annotations

import json
from typing import Callable

from app.domain.models import ToolDefinition, ToolInvocationRequest, ToolInvocationResult
from app.repositories.artifacts import ArtifactRepository
from app.services.browseract_ui_service_catalog import browseract_ui_service_definitions
from app.services.channel_runtime import ChannelRuntimeService
from app.services.evidence_runtime import EvidenceRuntimeService
from app.services.provider_registry import ProviderRegistryService
from app.services.tool_execution_artifact_module import ArtifactToolExecutionModule
from app.services.tool_execution_browseract_module import BrowserActToolExecutionModule
from app.services.tool_execution_common import (
    CONNECTOR_DISPATCH_IDEMPOTENCY_POLICY,
    CONNECTOR_DISPATCH_OPTIONAL_INPUT_FIELDS,
    CONNECTOR_DISPATCH_REQUIRED_INPUT_FIELDS,
    ToolExecutionError,
)
from app.services.tool_execution_connector_dispatch_module import ConnectorDispatchToolExecutionModule
from app.services.tool_execution_gemini_vortex_module import GeminiVortexToolExecutionModule
from app.services.tool_execution_magixai_module import MagixaiToolExecutionModule
from app.services.tool_execution_onemin_module import OneminToolExecutionModule
from app.services.tool_execution_comfyui_module import ComfyUIToolExecutionModule
from app.services.tool_execution_teable_module import TeableToolExecutionModule
from app.services.telegram_delivery import (
    resolve_primary_telegram_binding,
    send_telegram_audio_for_principal,
    send_telegram_document_for_principal,
    send_telegram_video_for_principal,
)
from app.services.tool_runtime import ToolRuntimeService

ToolExecutionHandler = Callable[[ToolInvocationRequest, ToolDefinition], ToolInvocationResult]


class ToolExecutionService:
    def __init__(
        self,
        *,
        tool_runtime: ToolRuntimeService,
        artifacts: ArtifactRepository,
        channel_runtime: ChannelRuntimeService | None = None,
        evidence_runtime: EvidenceRuntimeService | None = None,
        provider_registry: ProviderRegistryService | None = None,
    ) -> None:
        self._tool_runtime = tool_runtime
        self._provider_registry = provider_registry or ProviderRegistryService()
        self._handlers: dict[str, ToolExecutionHandler] = {}
        self._connector_dispatch_module = ConnectorDispatchToolExecutionModule(
            tool_runtime=tool_runtime,
            channel_runtime=channel_runtime,
        )
        self._browseract_module = BrowserActToolExecutionModule(
            tool_runtime=tool_runtime,
            connector_dispatch=self._connector_dispatch_module.adapter,
        )
        self._gemini_vortex_module = GeminiVortexToolExecutionModule(
            tool_runtime=tool_runtime,
        )
        self._magixai_module = MagixaiToolExecutionModule(
            tool_runtime=tool_runtime,
        )
        self._onemin_module = OneminToolExecutionModule(
            tool_runtime=tool_runtime,
        )
        self._comfyui_module = ComfyUIToolExecutionModule(
            tool_runtime=tool_runtime,
        )
        self._teable_module = TeableToolExecutionModule(
            tool_runtime=tool_runtime,
        )
        self._artifact_module = ArtifactToolExecutionModule(
            tool_runtime=tool_runtime,
            artifacts=artifacts,
            evidence_runtime=evidence_runtime,
        )
        self._builtin_capability_registrars: dict[tuple[str, str], Callable[[], None]] = {
            ("artifact_repository", "artifact_save"): self._register_builtin_artifact_repository,
            ("browseract", "account_facts"): self._register_builtin_browseract_extract,
            ("browseract", "account_inventory"): self._register_builtin_browseract_inventory,
            ("browseract", "workflow_spec_build"): self._register_builtin_browseract_workflow_spec,
            ("browseract", "workflow_spec_repair"): self._register_builtin_browseract_workflow_repair,
            ("browseract", "chatplayground_audit"): self._register_builtin_browseract_chatplayground_audit,
            ("browseract", "reasoned_patch_review"): self._register_builtin_browseract_chatplayground_audit,
            ("browseract", "gemini_web_generate"): self._register_builtin_browseract_gemini_web_generate,
            ("browseract", "onemin_billing_usage"): self._register_builtin_browseract_onemin_billing_usage,
            ("browseract", "onemin_member_reconciliation"): self._register_builtin_browseract_onemin_member_reconciliation,
            ("browseract", "crezlo_property_tour"): self._register_builtin_browseract_crezlo_property_tour,
            ("comfyui", "image_generate"): self._register_builtin_comfyui_image_generate,
            ("connector_dispatch", "dispatch"): self._register_builtin_connector_dispatch,
            ("gemini_vortex", "structured_generate"): self._register_builtin_gemini_vortex_structured_generate,
            ("magixai", "structured_generate"): self._register_builtin_magixai_structured_generate,
            ("onemin", "code_generate"): self._register_builtin_onemin_code_generate,
            ("onemin", "reasoned_patch_review"): self._register_builtin_onemin_reasoned_patch_review,
            ("onemin", "image_generate"): self._register_builtin_onemin_image_generate,
            ("onemin", "media_transform"): self._register_builtin_onemin_media_transform,
            ("onemin", "property_walkthrough_video"): self._register_builtin_onemin_property_walkthrough_video,
            ("ea", "scene_video_generate"): self._register_builtin_scene_video_generate,
            ("teable", "table_sync"): self._register_builtin_teable_table_sync,
        }
        for ui_service in browseract_ui_service_definitions():
            self._builtin_capability_registrars[("browseract", ui_service.capability_key)] = (
                lambda capability_key=ui_service.capability_key: self._register_builtin_browseract_ui_service(capability_key)
            )
        self._register_executable_provider_bindings()
        self._register_builtin_brain_router_structured_generate()
        self._register_builtin_brain_router_reasoned_patch_review()

    def register_handler(self, tool_name: str, handler: ToolExecutionHandler) -> None:
        key = str(tool_name or "").strip()
        if not key:
            raise ValueError("tool_name is required")
        self._handlers[key] = handler

    def execute_invocation(self, request: ToolInvocationRequest) -> ToolInvocationResult:
        requested_tool_name = str(request.tool_name or "").strip()
        tool_name = requested_tool_name
        context_json = dict(request.context_json or {})
        requested_principal_id = str(context_json.get("principal_id") or "").strip() or None
        try:
            route = self._provider_registry.route_tool_with_context(requested_tool_name, principal_id=requested_principal_id)
        except ToolExecutionError as exc:
            if (
                str(exc or "") != f"provider_tool_unavailable:{requested_tool_name}"
                or self._provider_registry.knows_tool(requested_tool_name)
            ):
                raise
        else:
            tool_name = route.tool_name
        if not tool_name:
            raise ToolExecutionError("tool_name_required")
        definition = self._tool_runtime.get_tool(tool_name)
        if definition is None:
            self._ensure_builtin_tool_registered(tool_name, principal_id=requested_principal_id)
            definition = self._tool_runtime.get_tool(tool_name)
        if definition is None:
            raise ToolExecutionError(f"tool_not_registered:{tool_name}")
        if not definition.enabled:
            raise ToolExecutionError(f"tool_disabled:{tool_name}")
        handler = self._handlers.get(tool_name)
        if handler is None:
            raise ToolExecutionError(f"tool_handler_missing:{tool_name}")
        if tool_name != requested_tool_name:
            request = ToolInvocationRequest(
                session_id=request.session_id,
                step_id=request.step_id,
                tool_name=tool_name,
                action_kind=request.action_kind,
                payload_json=dict(request.payload_json or {}),
                context_json=context_json,
            )
        result = handler(request, definition)
        if tool_name == "ea.scene_video_generate":
            result = self._normalize_scene_video_result(result)
        return self._maybe_send_generated_video_to_telegram(request=request, result=result)

    @staticmethod
    def _normalize_scene_video_result(result: ToolInvocationResult) -> ToolInvocationResult:
        from app.services.scene_video_contract import (
            normalize_scene_video_backend_provider,
            normalize_scene_video_contract_provider,
        )

        output_json = dict(result.output_json or {})
        receipt_json = dict(result.receipt_json or {})
        structured = dict(output_json.get("structured_output_json") or {})
        nested_structured = dict(structured.get("structured_output_json") or {})
        provider_backend_key = normalize_scene_video_backend_provider(
            output_json.get("provider_backend_key")
            or structured.get("provider_backend_key")
            or nested_structured.get("provider_backend_key")
            or receipt_json.get("provider_backend_key")
            or output_json.get("provider_key")
            or structured.get("provider_key")
            or nested_structured.get("provider_key")
            or receipt_json.get("provider_key"),
            default="mootion",
        )
        provider_key = normalize_scene_video_contract_provider(
            output_json.get("provider_key")
            or structured.get("provider_key")
            or nested_structured.get("provider_key")
            or receipt_json.get("provider_key")
            or provider_backend_key,
            default=provider_backend_key,
        )
        structured["provider_key"] = provider_key
        structured["provider_backend_key"] = provider_backend_key
        if nested_structured:
            nested_structured.setdefault("provider_backend_key", provider_backend_key)
            structured["structured_output_json"] = nested_structured
        output_json["structured_output_json"] = structured
        output_json["provider_key"] = provider_key
        output_json["provider_backend_key"] = provider_backend_key
        receipt_json.setdefault("provider_key", provider_key)
        receipt_json.setdefault("provider_backend_key", provider_backend_key)
        return ToolInvocationResult(
            tool_name=result.tool_name,
            action_kind=result.action_kind,
            target_ref=result.target_ref,
            output_json=output_json,
            receipt_json=receipt_json,
            artifacts=tuple(result.artifacts or ()),
            model_name=result.model_name,
            tokens_in=result.tokens_in,
            tokens_out=result.tokens_out,
            cost_usd=result.cost_usd,
        )

    @staticmethod
    def _looks_like_successful_video_output(output_json: dict[str, object]) -> bool:
        normalized_mime = str(output_json.get("mime_type") or "").strip().lower()
        if normalized_mime.startswith("video/"):
            return True
        structured = dict(output_json.get("structured_output_json") or {})
        for value in (
            output_json.get("asset_url"),
            output_json.get("download_url"),
            structured.get("asset_url"),
            structured.get("download_url"),
        ):
            normalized = str(value or "").strip().lower().split("?", 1)[0]
            if normalized.endswith((".mp4", ".mov", ".m4v", ".webm", ".avi", ".mkv")):
                return True
        return False

    @staticmethod
    def _looks_like_successful_audio_output(output_json: dict[str, object]) -> bool:
        normalized_mime = str(output_json.get("mime_type") or "").strip().lower()
        if normalized_mime.startswith("audio/"):
            return True
        structured = dict(output_json.get("structured_output_json") or {})
        for value in (
            output_json.get("asset_url"),
            output_json.get("download_url"),
            output_json.get("audio_url"),
            structured.get("asset_url"),
            structured.get("download_url"),
            structured.get("audio_url"),
        ):
            normalized = str(value or "").strip().lower().split("?", 1)[0]
            if normalized.endswith((".mp3", ".m4a", ".wav", ".ogg", ".flac", ".aac", ".opus")):
                return True
        return False

    @staticmethod
    def _looks_like_successful_document_output(output_json: dict[str, object]) -> bool:
        normalized_mime = str(output_json.get("mime_type") or "").strip().lower()
        if normalized_mime in {
            "application/pdf",
            "text/plain",
            "text/markdown",
            "application/json",
            "text/csv",
            "application/rtf",
        }:
            return True
        structured = dict(output_json.get("structured_output_json") or {})
        for value in (
            output_json.get("asset_url"),
            output_json.get("download_url"),
            output_json.get("document_url"),
            structured.get("asset_url"),
            structured.get("download_url"),
            structured.get("document_url"),
        ):
            normalized = str(value or "").strip().lower().split("?", 1)[0]
            if normalized.endswith((".pdf", ".txt", ".md", ".json", ".csv", ".rtf", ".doc", ".docx")):
                return True
        return False

    def _maybe_send_generated_video_to_telegram(
        self,
        *,
        request: ToolInvocationRequest,
        result: ToolInvocationResult,
    ) -> ToolInvocationResult:
        output_json = dict(result.output_json or {})
        principal_id = (
            str((request.context_json or {}).get("principal_id") or "").strip()
            or str((request.payload_json or {}).get("principal_id") or "").strip()
        )
        if not principal_id:
            return result
        if resolve_primary_telegram_binding(self._tool_runtime, principal_id=principal_id) is None:
            return result
        render_status = str(output_json.get("render_status") or dict(output_json.get("structured_output_json") or {}).get("render_status") or "").strip().lower()
        if render_status and render_status not in {"completed", "rendered", "ready", "success", "succeeded"}:
            return result
        from app.services.telegram_delivery import _extract_audio_ref, _extract_document_ref, _extract_video_ref

        media_kind = ""
        media_ref = ""
        if self._looks_like_successful_video_output(output_json):
            media_kind = "video"
            media_ref = _extract_video_ref(output_json=output_json)
        elif self._looks_like_successful_audio_output(output_json):
            media_kind = "audio"
            media_ref = _extract_audio_ref(output_json=output_json)
        elif self._looks_like_successful_document_output(output_json):
            media_kind = "document"
            media_ref = _extract_document_ref(output_json=output_json)
        if not media_kind or not media_ref:
            return result
        caption = "\n".join(
            part
            for part in (
                str(output_json.get("result_title") or "").strip(),
                str(output_json.get("public_url") or dict(output_json.get("structured_output_json") or {}).get("public_url") or "").strip(),
            )
            if part
        )
        delivery_json = dict(output_json.get("telegram_delivery_json") or {})
        try:
            if media_kind == "video":
                receipt = send_telegram_video_for_principal(
                    self._tool_runtime,
                    principal_id=principal_id,
                    video_ref=media_ref,
                    caption=caption,
                )
            elif media_kind == "audio":
                receipt = send_telegram_audio_for_principal(
                    self._tool_runtime,
                    principal_id=principal_id,
                    audio_ref=media_ref,
                    caption=caption,
                )
            else:
                receipt = send_telegram_document_for_principal(
                    self._tool_runtime,
                    principal_id=principal_id,
                    document_ref=media_ref,
                    caption=caption,
                )
            delivery_json.update(
                {
                    "status": "sent",
                    "kind": media_kind,
                    "chat_id": receipt.chat_id,
                    "message_ids": list(receipt.message_ids),
                    "media_ref": media_ref,
                }
            )
        except Exception as exc:
            delivery_json.update(
                {
                    "status": "failed",
                    "kind": media_kind,
                    "error": str(exc or "").strip() or "telegram_video_delivery_failed",
                    "media_ref": media_ref,
                }
            )
        output_json["telegram_delivery_json"] = delivery_json
        receipt_json = dict(result.receipt_json or {})
        receipt_json["telegram_delivery_json"] = dict(delivery_json)
        return ToolInvocationResult(
            tool_name=result.tool_name,
            action_kind=result.action_kind,
            target_ref=result.target_ref,
            output_json=output_json,
            receipt_json=receipt_json,
            artifacts=result.artifacts,
            model_name=result.model_name,
            tokens_in=result.tokens_in,
            tokens_out=result.tokens_out,
            cost_usd=result.cost_usd,
        )

    def _ensure_builtin_tool_registered(self, tool_name: str, *, principal_id: str | None = None) -> None:
        key = str(tool_name or "").strip()
        if not key:
            return
        try:
            route = self._provider_registry.route_tool_with_context(key, principal_id=principal_id)
        except ToolExecutionError:
            return
        registrar = self._builtin_capability_registrars.get((route.provider_key, route.capability_key))
        if registrar is not None:
            registrar()

    def _register_executable_provider_bindings(self) -> None:
        for binding in self._provider_registry.list_bindings():
            if not binding.executable:
                continue
            for capability in binding.capabilities:
                if not capability.executable:
                    continue
                registrar = self._builtin_capability_registrars.get((binding.provider_key, capability.capability_key))
                if registrar is not None:
                    registrar()

    def _register_builtin_artifact_repository(self) -> None:
        self._artifact_module.register_builtin(self.register_handler)

    def _register_builtin_browseract_extract(self) -> None:
        self._browseract_module.register_extract(self.register_handler)

    def _register_builtin_browseract_inventory(self) -> None:
        self._browseract_module.register_inventory(self.register_handler)

    def _register_builtin_browseract_workflow_spec(self) -> None:
        self._browseract_module.register_workflow_spec(self.register_handler)

    def _register_builtin_browseract_workflow_repair(self) -> None:
        self._browseract_module.register_workflow_repair(self.register_handler)

    def _register_builtin_browseract_chatplayground_audit(self) -> None:
        self._browseract_module.register_chatplayground_audit(self.register_handler)

    def _register_builtin_browseract_gemini_web_generate(self) -> None:
        self._browseract_module.register_gemini_web_generate(self.register_handler)

    def _register_builtin_browseract_onemin_billing_usage(self) -> None:
        self._browseract_module.register_onemin_billing_usage(self.register_handler)

    def _register_builtin_browseract_onemin_member_reconciliation(self) -> None:
        self._browseract_module.register_onemin_member_reconciliation(self.register_handler)

    def _register_builtin_browseract_crezlo_property_tour(self) -> None:
        self._browseract_module.register_crezlo_property_tour(self.register_handler)

    def _register_builtin_browseract_ui_service(self, capability_key: str) -> None:
        self._browseract_module.register_ui_service(
            self.register_handler,
            capability_key=capability_key,
        )

    def _register_builtin_connector_dispatch(self) -> None:
        self._connector_dispatch_module.register_builtin(self.register_handler)

    def _register_builtin_gemini_vortex_structured_generate(self) -> None:
        self._gemini_vortex_module.register_structured_generate(self.register_handler)

    def _register_builtin_magixai_structured_generate(self) -> None:
        self._magixai_module.register_structured_generate(self.register_handler)

    def _register_builtin_onemin_code_generate(self) -> None:
        self._onemin_module.register_code_generate(self.register_handler)

    def _register_builtin_onemin_reasoned_patch_review(self) -> None:
        self._onemin_module.register_reasoned_patch_review(self.register_handler)

    def _register_builtin_onemin_image_generate(self) -> None:
        self._onemin_module.register_image_generate(self.register_handler)

    def _register_builtin_comfyui_image_generate(self) -> None:
        self._comfyui_module.register_image_generate(self.register_handler)

    def _register_builtin_onemin_media_transform(self) -> None:
        self._onemin_module.register_media_transform(self.register_handler)

    def _register_builtin_onemin_property_walkthrough_video(self) -> None:
        self._onemin_module.register_property_walkthrough_video(self.register_handler)

    def _register_builtin_scene_video_generate(self) -> None:
        tool_name = "ea.scene_video_generate"
        if self._tool_runtime.get_tool(tool_name) is None:
            self._tool_runtime.upsert_tool(
                tool_name=tool_name,
                version="v1",
                input_schema_json={
                    "type": "object",
                    "required": ["provider_key", "context_kind", "title"],
                    "properties": {
                        "provider_key": {"type": "string"},
                        "context_kind": {"type": "string"},
                        "title": {"type": "string"},
                        "script_text": {"type": "string"},
                        "visual_style": {"type": "string"},
                        "camera_style": {"type": "string"},
                        "aspect_ratio": {"type": "string"},
                        "duration_seconds": {"type": "integer"},
                        "scene_count": {"type": "integer"},
                        "shot_pacing": {"type": "string"},
                        "audience": {"type": "string"},
                        "hook_line": {"type": "string"},
                        "closing_line": {"type": "string"},
                        "platform_target": {"type": "string"},
                        "cta": {"type": "string"},
                        "binding_id": {"type": "string"},
                        "run_url": {"type": "string"},
                        "workflow_id": {"type": "string"},
                        "timeout_seconds": {"type": "integer"},
                        "image_url": {"type": "string"},
                        "first_frame_path": {"type": "string"},
                        "model": {"type": "string"},
                        "tour_url": {"type": "string"},
                        "tour_context_json": {"type": "object"},
                        "property_facts_json": {"type": "object"},
                        "birthday_party_request": {"type": "boolean"},
                        "person_motion_hint": {"type": "string"},
                        "diorama_style_hint": {"type": "string"},
                        "readiness_only": {"type": "boolean"},
                        "telegram_delivery_requested": {"type": "boolean"},
                    },
                },
                output_schema_json={"type": "object"},
                policy_json={"builtin": True, "action_kind": "video.generate", "capability": "scene_video_generate"},
                approval_default="none",
                enabled=True,
            )

        def _normalize_provider(value: object) -> str:
            from app.services.scene_video_contract import normalize_scene_video_backend_provider

            return normalize_scene_video_backend_provider(value, default="mootion")

        def _candidate_urls(value: object) -> list[str]:
            found: list[str] = []
            if isinstance(value, str):
                candidate = value.strip()
                lowered = candidate.lower().split("?", 1)[0]
                if lowered.endswith((".mp4", ".webm", ".mov", ".m4v", ".avi", ".mkv")):
                    found.append(candidate)
            elif isinstance(value, dict):
                for nested in value.values():
                    found.extend(_candidate_urls(nested))
            elif isinstance(value, (list, tuple, set)):
                for nested in value:
                    found.extend(_candidate_urls(nested))
            deduped: list[str] = []
            seen: set[str] = set()
            for candidate in found:
                if candidate in seen:
                    continue
                seen.add(candidate)
                deduped.append(candidate)
            return deduped

        def _contract_provider_key(value: object) -> str:
            from app.services.scene_video_contract import normalize_scene_video_contract_provider

            return normalize_scene_video_contract_provider(value, default="mootion")

        def _scene_seed_prompt(payload: dict[str, object], *, title: str) -> str:
            prompt = str(payload.get("seed_image_prompt") or "").strip()
            if prompt:
                return prompt
            prompt_parts = [
                f"Create one cinematic first-frame still for the motion scene titled {title or 'Scene video'}.",
                str(payload.get("script_text") or payload.get("prompt") or payload.get("source_text") or "").strip(),
            ]
            visual_style = str(payload.get("visual_style") or "").strip()
            camera_style = str(payload.get("camera_style") or "").strip()
            if visual_style:
                prompt_parts.append(f"Visual style: {visual_style}.")
            if camera_style:
                prompt_parts.append(f"Camera style: {camera_style}.")
            prompt_parts.append(
                "Single coherent still frame only. No text, no watermark, no split panels, no storyboard grid, and no collage."
            )
            return " ".join(part for part in prompt_parts if part).strip()

        def _ensure_scene_reference(
            *,
            request: ToolInvocationRequest,
            payload: dict[str, object],
            title: str,
            nested_context: dict[str, object],
        ) -> dict[str, object]:
            image_url = str(payload.get("image_url") or "").strip()
            first_frame_path = str(payload.get("first_frame_path") or "").strip()
            if image_url or first_frame_path:
                return {
                    "image_url": image_url,
                    "first_frame_path": first_frame_path,
                    "seed_image_generated": False,
                    "seed_image_url": image_url,
                    "seed_tool_name": "",
                    "seed_structured_output_json": {},
                    "seed_artifacts": (),
                    "seed_model_name": "",
                    "seed_tokens_in": 0,
                    "seed_tokens_out": 0,
                    "seed_cost_usd": 0.0,
                }
            seed_prompt = _scene_seed_prompt(payload, title=title)
            if not seed_prompt:
                raise ToolExecutionError("scene_video_seed_prompt_missing")
            seed = self.execute_invocation(
                ToolInvocationRequest(
                    session_id=request.session_id,
                    step_id=request.step_id,
                    tool_name="provider.onemin.image_generate",
                    action_kind="image.generate",
                    payload_json={
                        "prompt": seed_prompt,
                        "aspect_ratio": str(payload.get("aspect_ratio") or "16:9").strip() or "16:9",
                        "output_format": "png",
                        "quality": "low",
                    },
                    context_json=nested_context,
                )
            )
            seed_output = dict(seed.output_json or {})
            seed_structured = dict(seed_output.get("structured_output_json") or {})
            seed_asset_urls = seed_output.get("asset_urls") or seed_structured.get("asset_urls") or ()
            seed_image_url = ""
            if isinstance(seed_asset_urls, (list, tuple)):
                for candidate in seed_asset_urls:
                    candidate_url = str(candidate or "").strip()
                    if candidate_url:
                        seed_image_url = candidate_url
                        break
            if not seed_image_url:
                raise ToolExecutionError("scene_video_seed_image_missing")
            return {
                "image_url": seed_image_url,
                "first_frame_path": "",
                "seed_image_generated": True,
                "seed_image_url": seed_image_url,
                "seed_tool_name": seed.tool_name,
                "seed_structured_output_json": seed_structured,
                "seed_artifacts": tuple(seed.artifacts or ()),
                "seed_model_name": str(seed.model_name or "").strip(),
                "seed_tokens_in": int(seed.tokens_in or 0),
                "seed_tokens_out": int(seed.tokens_out or 0),
                "seed_cost_usd": float(seed.cost_usd or 0.0),
            }

        def _magicfit_aspect_label(value: object) -> str:
            normalized = str(value or "").strip().lower()
            if normalized in {"9:16", "portrait", "portrait (9:16)"}:
                return "Portrait (9:16)"
            if normalized in {"1:1", "square"}:
                return "1:1"
            if normalized == "4:3":
                return "4:3"
            if normalized == "3:4":
                return "3:4"
            if normalized == "21:9":
                return "21:9"
            return "Landscape (16:9)"

        def _materialize_first_frame_path(*, image_url: str, first_frame_path: str, work_dir: object) -> str:
            from pathlib import Path
            from urllib.parse import urlparse
            from urllib.request import urlopen

            if first_frame_path:
                return first_frame_path
            candidate = str(image_url or "").strip()
            if not candidate:
                return ""
            candidate_path = Path(candidate).expanduser()
            if candidate_path.exists():
                return str(candidate_path.resolve())
            parsed = urlparse(candidate)
            suffix = Path(parsed.path).suffix.lower() or ".png"
            target_path = Path(work_dir) / f"scene-first-frame{suffix}"
            with urlopen(candidate, timeout=120) as response:
                target_path.write_bytes(response.read())
            return str(target_path)

        def handler(request: ToolInvocationRequest, definition: ToolDefinition) -> ToolInvocationResult:
            payload = dict(request.payload_json or {})
            provider_key = _normalize_provider(payload.get("provider_key") or payload.get("walkthrough_provider_key") or "")
            context_kind = str(
                payload.get("context_kind")
                or ("property_walkthrough" if str(payload.get("tour_url") or "").strip() else "scene_briefing")
            ).strip().lower() or "scene_briefing"
            title = str(payload.get("title") or "Scene video").strip() or "Scene video"
            if bool(payload.get("readiness_only")):
                from app.services.scene_video_contract import scene_video_provider_runtime_readiness

                runtime_readiness = scene_video_provider_runtime_readiness(provider_key)
                telegram_delivery_requested = bool(payload.get("telegram_delivery_requested") or payload.get("telegram_delivery"))
                principal_id = str(dict(request.context_json or {}).get("principal_id") or payload.get("principal_id") or "").strip()
                telegram_readiness = {
                    "requested": telegram_delivery_requested,
                    "status": "not_requested",
                    "principal_id": principal_id,
                    "binding_configured": False,
                    "reason": "",
                }
                if telegram_delivery_requested:
                    if not principal_id:
                        telegram_readiness["status"] = "blocked"
                        telegram_readiness["reason"] = "principal_id_missing"
                    else:
                        telegram_binding = resolve_primary_telegram_binding(self._tool_runtime, principal_id=principal_id)
                        telegram_readiness["binding_configured"] = telegram_binding is not None
                        telegram_readiness["status"] = "ready" if telegram_binding is not None else "blocked"
                        telegram_readiness["reason"] = "" if telegram_binding is not None else "telegram_binding_not_found"
                blockers = list(runtime_readiness.get("blockers") or [])
                if telegram_readiness["status"] == "blocked":
                    blockers.append(str(telegram_readiness.get("reason") or "telegram_delivery_blocked"))
                render_status = "ready" if not blockers else "blocked"
                normalized = {
                    "deliverable_type": "scene_video_packet",
                    "provider_key": str(runtime_readiness.get("provider_key") or _contract_provider_key(provider_key)),
                    "provider_backend_key": str(runtime_readiness.get("provider_backend_key") or provider_key),
                    "render_status": render_status,
                    "asset_url": "",
                    "download_url": "",
                    "video_url": "",
                    "flythrough_url": "",
                    "editor_url": "",
                    "reason": ",".join(blockers),
                    "runtime_readiness_json": runtime_readiness,
                    "telegram_delivery_readiness_json": telegram_readiness,
                    "structured_output_json": {
                        "runtime_readiness_json": runtime_readiness,
                        "telegram_delivery_readiness_json": telegram_readiness,
                    },
                }
                normalized_text = json.dumps(normalized, ensure_ascii=False)
                return ToolInvocationResult(
                    tool_name=definition.tool_name,
                    action_kind="video.generate",
                    target_ref="",
                    output_json={
                        "normalized_text": normalized_text,
                        "preview_text": normalized_text[:280],
                        "mime_type": "application/json",
                        "structured_output_json": normalized,
                        "provider_key": normalized["provider_key"],
                        "provider_backend_key": normalized["provider_backend_key"],
                        "render_status": normalized["render_status"],
                        "runtime_readiness_json": runtime_readiness,
                        "telegram_delivery_readiness_json": telegram_readiness,
                    },
                    receipt_json={
                        "provider_key": normalized["provider_key"],
                        "provider_backend_key": normalized["provider_backend_key"],
                        "context_kind": context_kind,
                        "runtime_readiness_json": runtime_readiness,
                        "telegram_delivery_readiness_json": telegram_readiness,
                    },
                )
            if context_kind == "property_walkthrough":
                from app.product.service import _hosted_property_tour_video_delivery, _render_property_flythrough_into_hosted_tour

                tour_url = str(payload.get("tour_url") or "").strip()
                if not tour_url:
                    raise ToolExecutionError("scene_video_tour_url_missing")
                tour_context_json = (
                    dict(payload.get("tour_context_json") or {})
                    if isinstance(payload.get("tour_context_json"), dict)
                    else {}
                )
                rendered = _render_property_flythrough_into_hosted_tour(
                    tour_url=tour_url,
                    title=title,
                    property_facts=dict(payload.get("property_facts_json") or {}),
                    actor=str(payload.get("actor") or "scene_video_skill").strip(),
                    birthday_party_request=bool(payload.get("birthday_party_request")),
                    person_motion_hint=str(payload.get("person_motion_hint") or "").strip(),
                    diorama_style_hint=str(payload.get("diorama_style_hint") or "").strip(),
                    preferred_provider_key=provider_key,
                    tour_context_json=tour_context_json,
                )
                delivery = _hosted_property_tour_video_delivery(tour_url)
                video_url = str(delivery.get("video_url") or rendered.get("video_url") or "").strip()
                flythrough_url = str(delivery.get("flythrough_url") or rendered.get("flythrough_url") or "").strip()
                provider_backend_key = str(
                    rendered.get("media_route_provider_key")
                    or delivery.get("provider_key")
                    or rendered.get("provider_key")
                    or provider_key
                ).strip()
                normalized = {
                    "deliverable_type": "scene_video_packet",
                    "provider_key": _contract_provider_key(provider_backend_key),
                    "provider_backend_key": provider_backend_key,
                    "render_status": str(rendered.get("status") or "").strip().lower() or "unknown",
                    "video_url": video_url,
                    "asset_url": video_url,
                    "download_url": video_url,
                    "flythrough_url": flythrough_url,
                    "editor_url": str(rendered.get("editor_url") or "").strip(),
                    "reason": str(rendered.get("reason") or "").strip(),
                    "tour_url": tour_url,
                    "tour_context_json": tour_context_json,
                    "structured_output_json": {
                        **dict(rendered or {}),
                        "provider_backend_key": provider_backend_key,
                        "tour_context_json": tour_context_json,
                    },
                }
                normalized_text = json.dumps(normalized, ensure_ascii=False)
                return ToolInvocationResult(
                    tool_name=definition.tool_name,
                    action_kind="video.generate",
                    target_ref=flythrough_url or video_url or tour_url,
                    output_json={
                        "normalized_text": normalized_text,
                        "preview_text": normalized_text[:280],
                        "mime_type": "application/json",
                        "structured_output_json": normalized,
                        "provider_key": normalized["provider_key"],
                        "provider_backend_key": normalized["provider_backend_key"],
                        "render_status": normalized["render_status"],
                        "video_url": video_url,
                        "asset_url": video_url,
                        "download_url": video_url,
                        "flythrough_url": flythrough_url,
                        "editor_url": normalized["editor_url"],
                        "tour_context_json": tour_context_json,
                    },
                    receipt_json={
                        "provider_key": normalized["provider_key"],
                        "provider_backend_key": normalized["provider_backend_key"],
                        "context_kind": context_kind,
                        "reason": normalized["reason"],
                        "tour_context_present": bool(tour_context_json),
                    },
                )
            nested_context = dict(request.context_json or {})
            nested_context.pop("telegram_delivery", None)
            from app.services.scene_video_contract import scene_video_provider_runtime_readiness

            runtime_readiness = scene_video_provider_runtime_readiness(provider_key)
            if not bool(runtime_readiness.get("ready")):
                telegram_delivery_requested = bool(payload.get("telegram_delivery_requested") or payload.get("telegram_delivery"))
                principal_id = str(dict(request.context_json or {}).get("principal_id") or payload.get("principal_id") or "").strip()
                telegram_readiness = {
                    "requested": telegram_delivery_requested,
                    "status": "not_requested",
                    "principal_id": principal_id,
                    "binding_configured": False,
                    "reason": "",
                }
                if telegram_delivery_requested:
                    if not principal_id:
                        telegram_readiness["status"] = "blocked"
                        telegram_readiness["reason"] = "principal_id_missing"
                    else:
                        telegram_binding = resolve_primary_telegram_binding(self._tool_runtime, principal_id=principal_id)
                        telegram_readiness["binding_configured"] = telegram_binding is not None
                        telegram_readiness["status"] = "ready" if telegram_binding is not None else "blocked"
                        telegram_readiness["reason"] = "" if telegram_binding is not None else "telegram_binding_not_found"
                blockers = list(runtime_readiness.get("blockers") or [])
                if telegram_readiness["status"] == "blocked":
                    blockers.append(str(telegram_readiness.get("reason") or "telegram_delivery_blocked"))
                normalized = {
                    "deliverable_type": "scene_video_packet",
                    "provider_key": str(runtime_readiness.get("provider_key") or _contract_provider_key(provider_key)),
                    "provider_backend_key": str(runtime_readiness.get("provider_backend_key") or provider_key),
                    "render_status": "blocked",
                    "asset_url": "",
                    "download_url": "",
                    "video_url": "",
                    "flythrough_url": "",
                    "editor_url": "",
                    "reason": ",".join(blockers),
                    "runtime_readiness_json": runtime_readiness,
                    "telegram_delivery_readiness_json": telegram_readiness,
                    "structured_output_json": {
                        "provider_backend_key": str(runtime_readiness.get("provider_backend_key") or provider_key),
                        "runtime_readiness_json": runtime_readiness,
                        "telegram_delivery_readiness_json": telegram_readiness,
                    },
                }
                normalized_text = json.dumps(normalized, ensure_ascii=False)
                return ToolInvocationResult(
                    tool_name=definition.tool_name,
                    action_kind="video.generate",
                    target_ref="",
                    output_json={
                        "normalized_text": normalized_text,
                        "preview_text": normalized_text[:280],
                        "mime_type": "application/json",
                        "structured_output_json": normalized,
                        "provider_key": normalized["provider_key"],
                        "provider_backend_key": normalized["provider_backend_key"],
                        "render_status": normalized["render_status"],
                        "runtime_readiness_json": runtime_readiness,
                        "telegram_delivery_readiness_json": telegram_readiness,
                    },
                    receipt_json={
                        "provider_key": normalized["provider_key"],
                        "provider_backend_key": normalized["provider_backend_key"],
                        "context_kind": context_kind,
                        "runtime_readiness_json": runtime_readiness,
                        "telegram_delivery_readiness_json": telegram_readiness,
                    },
                )
            if provider_key == "mootion":
                nested = self.execute_invocation(
                    ToolInvocationRequest(
                        session_id=request.session_id,
                        step_id=request.step_id,
                        tool_name="browseract.mootion_movie",
                        action_kind="movie.render",
                        payload_json={
                            "script_text": str(payload.get("script_text") or payload.get("source_text") or "").strip(),
                            "visual_style": str(payload.get("visual_style") or "").strip(),
                            "camera_style": str(payload.get("camera_style") or "").strip(),
                            "aspect_ratio": str(payload.get("aspect_ratio") or "").strip(),
                            "duration_seconds": payload.get("duration_seconds"),
                            "scene_count": payload.get("scene_count"),
                            "shot_pacing": payload.get("shot_pacing"),
                            "title": title,
                            "audience": payload.get("audience"),
                            "hook_line": payload.get("hook_line"),
                            "closing_line": payload.get("closing_line"),
                            "platform_target": payload.get("platform_target"),
                            "cta": payload.get("cta"),
                            "binding_id": payload.get("binding_id"),
                            "run_url": payload.get("run_url"),
                            "workflow_id": payload.get("workflow_id"),
                            "timeout_seconds": payload.get("timeout_seconds"),
                        },
                        context_json=nested_context,
                    )
                )
                nested_output = dict(nested.output_json or {})
                nested_structured = dict(nested_output.get("structured_output_json") or {})
                asset_url = str(
                    nested_output.get("asset_url")
                    or nested_output.get("download_url")
                    or nested_structured.get("asset_url")
                    or nested_structured.get("download_url")
                    or nested.target_ref
                    or ""
                ).strip()
                normalized = {
                    "deliverable_type": "scene_video_packet",
                    "provider_key": "mootion",
                    "provider_backend_key": "mootion",
                    "render_status": str(nested_output.get("render_status") or nested_structured.get("render_status") or "").strip().lower() or "unknown",
                    "video_url": asset_url,
                    "asset_url": asset_url,
                    "download_url": asset_url,
                    "flythrough_url": "",
                    "editor_url": str(nested_output.get("editor_url") or nested_structured.get("editor_url") or "").strip(),
                    "reason": "",
                    "structured_output_json": {
                        **nested_structured,
                        "provider_backend_key": "mootion",
                    },
                }
                normalized_text = json.dumps(normalized, ensure_ascii=False)
                return ToolInvocationResult(
                    tool_name=definition.tool_name,
                    action_kind="video.generate",
                    target_ref=asset_url or nested.target_ref,
                    output_json={
                        "normalized_text": normalized_text,
                        "preview_text": normalized_text[:280],
                        "mime_type": "application/json",
                        "structured_output_json": normalized,
                        "provider_key": normalized["provider_key"],
                        "provider_backend_key": normalized["provider_backend_key"],
                        "render_status": normalized["render_status"],
                        "video_url": asset_url,
                        "asset_url": asset_url,
                        "download_url": asset_url,
                        "editor_url": normalized["editor_url"],
                    },
                    receipt_json={
                        "provider_key": "mootion",
                        "provider_backend_key": "mootion",
                        "delegate_tool_name": nested.tool_name,
                        "context_kind": context_kind,
                    },
                    artifacts=nested.artifacts,
                    model_name=nested.model_name,
                    tokens_in=nested.tokens_in,
                    tokens_out=nested.tokens_out,
                    cost_usd=nested.cost_usd,
                )
            prompt = str(payload.get("script_text") or payload.get("prompt") or payload.get("source_text") or "").strip()
            if not prompt:
                raise ToolExecutionError(f"scene_video_prompt_missing:{provider_key or 'scene'}")
            scene_reference = _ensure_scene_reference(
                request=request,
                payload=payload,
                title=title,
                nested_context=nested_context,
            )
            image_url = str(scene_reference.get("image_url") or "").strip()
            first_frame_path = str(scene_reference.get("first_frame_path") or "").strip()
            if provider_key == "magicfit":
                import math
                import subprocess
                import sys
                import tempfile
                from pathlib import Path

                from app.services.scene_video_contract import resolve_scene_video_script_path

                script_path = resolve_scene_video_script_path("render_magicfit_property_flythrough.py")
                if not script_path.exists():
                    raise ToolExecutionError("scene_video_magicfit_script_missing")
                timeout_seconds = int(payload.get("timeout_seconds") or 0)
                work_dir = Path(tempfile.mkdtemp(prefix="ea-scene-video-magicfit-")).resolve()
                out_path = (work_dir / "scene-video.mp4").resolve()
                state_path = (work_dir / "scene-video.json").resolve()
                local_first_frame = _materialize_first_frame_path(
                    image_url=image_url,
                    first_frame_path=first_frame_path,
                    work_dir=work_dir,
                )
                if not local_first_frame:
                    raise ToolExecutionError("scene_video_reference_image_required:magicfit")
                command = [
                    str(sys.executable or "python3"),
                    str(script_path),
                    "--prompt",
                    prompt,
                    "--out",
                    str(out_path),
                    "--duration",
                    str(int(payload.get("duration_seconds") or 10)),
                    "--aspect-label",
                    _magicfit_aspect_label(payload.get("aspect_ratio")),
                    "--timeout-minutes",
                    str(max(3, int(math.ceil(timeout_seconds / 60.0))) if timeout_seconds else 18),
                    "--state-json",
                    str(state_path),
                    "--first-frame",
                    local_first_frame,
                ]
                model_label = str(payload.get("model") or "").strip()
                if model_label:
                    command.extend(["--model-label", model_label])
                try:
                    completed = subprocess.run(
                        command,
                        capture_output=True,
                        text=True,
                        timeout=max(timeout_seconds + 90, 300) if timeout_seconds else 1500,
                        check=False,
                    )
                except subprocess.TimeoutExpired as exc:
                    raise ToolExecutionError("scene_video_magicfit_timeout") from exc
                if completed.returncode != 0:
                    tail = str(completed.stderr or completed.stdout or "").strip().replace("\n", " ")
                    raise ToolExecutionError(f"scene_video_magicfit_failed:{tail[-400:] or 'subprocess_failed'}")
                magicfit_state: dict[str, object] = {}
                try:
                    if state_path.exists():
                        loaded_state = json.loads(state_path.read_text(encoding="utf-8"))
                        if isinstance(loaded_state, dict):
                            magicfit_state = dict(loaded_state)
                except Exception:
                    magicfit_state = {}
                if not magicfit_state:
                    for raw_line in reversed(str(completed.stdout or "").splitlines()):
                        candidate_line = raw_line.strip()
                        if not candidate_line.startswith("{"):
                            continue
                        try:
                            loaded_state = json.loads(candidate_line)
                        except Exception:
                            continue
                        if isinstance(loaded_state, dict):
                            magicfit_state = dict(loaded_state)
                            break
                asset_url = str(magicfit_state.get("video_output_url") or "").strip() or str(out_path)
                magicfit_structured = {
                    **magicfit_state,
                    "provider_key": "magicfit",
                    "provider_backend_key": "magicfit",
                    "seed_image_generated": bool(scene_reference.get("seed_image_generated")),
                    "seed_image_url": str(scene_reference.get("seed_image_url") or "").strip(),
                    "seed_tool_name": str(scene_reference.get("seed_tool_name") or "").strip(),
                    "local_first_frame_path": local_first_frame,
                }
                normalized = {
                    "deliverable_type": "scene_video_packet",
                    "provider_key": "magicfit",
                    "provider_backend_key": "magicfit",
                    "render_status": "completed",
                    "video_url": asset_url,
                    "asset_url": asset_url,
                    "download_url": asset_url,
                    "flythrough_url": "",
                    "editor_url": str(magicfit_state.get("page_url") or "").strip(),
                    "reason": "",
                    "structured_output_json": magicfit_structured,
                }
                normalized_text = json.dumps(normalized, ensure_ascii=False)
                return ToolInvocationResult(
                    tool_name=definition.tool_name,
                    action_kind="video.generate",
                    target_ref=asset_url,
                    output_json={
                        "normalized_text": normalized_text,
                        "preview_text": normalized_text[:280],
                        "mime_type": "application/json",
                        "structured_output_json": normalized,
                        "provider_key": normalized["provider_key"],
                        "provider_backend_key": normalized["provider_backend_key"],
                        "render_status": normalized["render_status"],
                        "video_url": asset_url,
                        "asset_url": asset_url,
                        "download_url": asset_url,
                        "editor_url": normalized["editor_url"],
                    },
                    receipt_json={
                        "provider_key": "magicfit",
                        "context_kind": context_kind,
                        "seed_image_generated": bool(scene_reference.get("seed_image_generated")),
                        "seed_tool_name": str(scene_reference.get("seed_tool_name") or "").strip(),
                    },
                    artifacts=tuple(scene_reference.get("seed_artifacts") or ()),
                    model_name=str(scene_reference.get("seed_model_name") or "").strip() or None,
                    tokens_in=int(scene_reference.get("seed_tokens_in") or 0),
                    tokens_out=int(scene_reference.get("seed_tokens_out") or 0),
                    cost_usd=float(scene_reference.get("seed_cost_usd") or 0.0),
                )
            nested = self.execute_invocation(
                ToolInvocationRequest(
                    session_id=request.session_id,
                    step_id=request.step_id,
                    tool_name="provider.onemin.property_walkthrough_video",
                    action_kind="video.generate",
                    payload_json={
                        "prompt": prompt,
                        "source_text": prompt,
                        "image_url": image_url,
                        "first_frame_path": first_frame_path,
                        "model": payload.get("model"),
                        "model_order": payload.get("model_order") or payload.get("modelOrder"),
                        "duration": payload.get("duration_seconds"),
                        "timeout_seconds": payload.get("timeout_seconds"),
                    },
                    context_json=nested_context,
                )
            )
            nested_output = dict(nested.output_json or {})
            nested_structured = dict(nested_output.get("structured_output_json") or {})
            candidate_urls = _candidate_urls(nested_output) or _candidate_urls(nested_structured)
            asset_url = str(candidate_urls[0] if candidate_urls else nested.target_ref).strip()
            normalized = {
                "deliverable_type": "scene_video_packet",
                "provider_key": "omagic",
                "provider_backend_key": "onemin_i2v",
                "render_status": str(nested_output.get("render_status") or nested_structured.get("render_status") or "completed").strip().lower(),
                "video_url": asset_url,
                "asset_url": asset_url,
                "download_url": asset_url,
                "flythrough_url": "",
                "editor_url": str(nested_output.get("editor_url") or nested_structured.get("editor_url") or "").strip(),
                "reason": "",
                "structured_output_json": {
                    **nested_structured,
                    "provider_backend_key": "onemin_i2v",
                    "seed_image_generated": bool(scene_reference.get("seed_image_generated")),
                    "seed_image_url": str(scene_reference.get("seed_image_url") or "").strip(),
                    "seed_tool_name": str(scene_reference.get("seed_tool_name") or "").strip(),
                },
            }
            normalized_text = json.dumps(normalized, ensure_ascii=False)
            return ToolInvocationResult(
                tool_name=definition.tool_name,
                action_kind="video.generate",
                target_ref=asset_url or nested.target_ref,
                output_json={
                    "normalized_text": normalized_text,
                    "preview_text": normalized_text[:280],
                    "mime_type": "application/json",
                    "structured_output_json": normalized,
                    "provider_key": normalized["provider_key"],
                    "provider_backend_key": normalized["provider_backend_key"],
                    "render_status": normalized["render_status"],
                    "video_url": asset_url,
                    "asset_url": asset_url,
                    "download_url": asset_url,
                    "editor_url": normalized["editor_url"],
                },
                receipt_json={
                    "provider_key": "omagic",
                    "provider_backend_key": "onemin_i2v",
                    "delegate_tool_name": nested.tool_name,
                    "context_kind": context_kind,
                    "seed_image_generated": bool(scene_reference.get("seed_image_generated")),
                    "seed_tool_name": str(scene_reference.get("seed_tool_name") or "").strip(),
                },
                artifacts=tuple(scene_reference.get("seed_artifacts") or ()) + tuple(nested.artifacts or ()),
                model_name=nested.model_name or str(scene_reference.get("seed_model_name") or "").strip() or None,
                tokens_in=int(scene_reference.get("seed_tokens_in") or 0) + int(nested.tokens_in or 0),
                tokens_out=int(scene_reference.get("seed_tokens_out") or 0) + int(nested.tokens_out or 0),
                cost_usd=float(scene_reference.get("seed_cost_usd") or 0.0) + float(nested.cost_usd or 0.0),
            )

        self.register_handler(tool_name, handler)

    def _register_builtin_teable_table_sync(self) -> None:
        self._teable_module.register_table_sync(self.register_handler)

    def _register_builtin_brain_router_structured_generate(self) -> None:
        self._register_builtin_brain_router_tool(
            tool_name="provider.brain_router.structured_generate",
            action_kind="content.generate",
            capability_key="structured_generate",
        )

    def _register_builtin_brain_router_reasoned_patch_review(self) -> None:
        self._register_builtin_brain_router_tool(
            tool_name="provider.brain_router.reasoned_patch_review",
            action_kind="audit.review_light",
            capability_key="reasoned_patch_review",
        )

    def _register_builtin_brain_router_tool(
        self,
        *,
        tool_name: str,
        action_kind: str,
        capability_key: str,
    ) -> None:
        self._tool_runtime.upsert_tool(
            tool_name=tool_name,
            version="builtin-brain-router-v1",
            input_schema_json={"type": "object"},
            output_schema_json={"type": "object"},
            policy_json={
                "logical_tool": True,
                "brain_router": True,
                "capability_key": capability_key,
                "action_kind": action_kind,
            },
            approval_default="none",
            enabled=True,
        )

        def _handler(request: ToolInvocationRequest, definition: ToolDefinition) -> ToolInvocationResult:
            return self._execute_brain_router_capability(
                request=request,
                definition=definition,
                capability_key=capability_key,
            )

        self.register_handler(tool_name, _handler)

    def _execute_brain_router_capability(
        self,
        *,
        request: ToolInvocationRequest,
        definition: ToolDefinition,
        capability_key: str,
    ) -> ToolInvocationResult:
        payload_json = dict(request.payload_json or {})
        context_json = dict(request.context_json or {})
        principal_id = str(context_json.get("principal_id") or "").strip() or None
        provider_hints = tuple(
            str(value or "").strip()
            for value in (payload_json.get("provider_hint_order") or ())
            if str(value or "").strip()
        )
        allowed_tools = tuple(
            str(value or "").strip()
            for value in (payload_json.get("allowed_tools") or ())
            if str(value or "").strip()
        )
        profile_name = str(payload_json.get("brain_profile") or "").strip()
        if not profile_name and capability_key == "reasoned_patch_review":
            profile_name = str(payload_json.get("posthoc_review_profile") or "").strip()
        if not profile_name:
            profile_name = "review_light" if capability_key == "reasoned_patch_review" else "easy"
        effective_action_kind = str(request.action_kind or "").strip()
        if capability_key == "reasoned_patch_review":
            inferred_review_action = "audit.jury" if profile_name == "audit" else "audit.review_light"
            if not effective_action_kind or effective_action_kind == "audit.review_light":
                effective_action_kind = inferred_review_action
        elif not effective_action_kind:
            effective_action_kind = str((definition.policy_json or {}).get("action_kind") or "").strip()
        route = self._provider_registry.route_brain_profile_capability_with_context(
            profile_name=profile_name,
            capability_key=capability_key,
            principal_id=principal_id,
            allowed_tools=allowed_tools,
            require_executable=True,
            provider_hints=provider_hints,
        )
        self._ensure_builtin_tool_registered(route.tool_name, principal_id=principal_id)
        routed_definition = self._tool_runtime.get_tool(route.tool_name)
        if routed_definition is None:
            raise ToolExecutionError(f"tool_not_registered:{route.tool_name}")
        if not routed_definition.enabled:
            raise ToolExecutionError(f"tool_disabled:{route.tool_name}")
        routed_handler = self._handlers.get(route.tool_name)
        if routed_handler is None:
            raise ToolExecutionError(f"tool_handler_missing:{route.tool_name}")
        routed_payload_json = dict(payload_json)
        routed_payload_json.setdefault("brain_profile", profile_name)
        routed_payload_json["routed_provider_key"] = route.provider_key
        routed_payload_json["routed_capability_key"] = route.capability_key
        result = routed_handler(
            ToolInvocationRequest(
                session_id=request.session_id,
                step_id=request.step_id,
                tool_name=route.tool_name,
                action_kind=effective_action_kind,
                payload_json=routed_payload_json,
                context_json=context_json,
            ),
            routed_definition,
        )
        output_json = self._normalize_brain_router_output(
            capability_key=capability_key,
            profile_name=profile_name,
            output_json=dict(result.output_json or {}),
        )
        route_fallback_used = bool(provider_hints and route.provider_key != provider_hints[0])
        output_json.setdefault("brain_profile", profile_name)
        output_json.setdefault("posthoc_review_profile", str(payload_json.get("posthoc_review_profile") or "").strip())
        output_json.setdefault("fallback_brain_profile", str(payload_json.get("fallback_brain_profile") or "").strip())
        output_json.setdefault("routed_provider_key", route.provider_key)
        output_json.setdefault("routed_capability_key", route.capability_key)
        output_json.setdefault("route_fallback_used", route_fallback_used)
        receipt_json = dict(result.receipt_json or {})
        receipt_json.setdefault("logical_tool_name", definition.tool_name)
        receipt_json.setdefault("brain_profile", profile_name)
        receipt_json.setdefault("posthoc_review_profile", str(payload_json.get("posthoc_review_profile") or "").strip())
        receipt_json.setdefault("fallback_brain_profile", str(payload_json.get("fallback_brain_profile") or "").strip())
        receipt_json.setdefault("routed_provider_key", route.provider_key)
        receipt_json.setdefault("routed_capability_key", route.capability_key)
        receipt_json.setdefault("route_fallback_used", route_fallback_used)
        return ToolInvocationResult(
            tool_name=result.tool_name,
            action_kind=result.action_kind,
            target_ref=result.target_ref,
            output_json=output_json,
            receipt_json=receipt_json,
            artifacts=tuple(result.artifacts or ()),
            model_name=result.model_name,
            tokens_in=result.tokens_in,
            tokens_out=result.tokens_out,
            cost_usd=result.cost_usd,
        )

    def _normalize_brain_router_output(
        self,
        *,
        capability_key: str,
        profile_name: str,
        output_json: dict[str, object],
    ) -> dict[str, object]:
        normalized = dict(output_json or {})
        structured = dict(normalized.get("structured_output_json") or {})
        text = str(normalized.get("normalized_text") or "").strip()
        if capability_key == "structured_generate" and str(profile_name or "").strip() == "groundwork":
            structured["format"] = "groundwork_brief"
            structured["plan"] = self._normalize_brain_router_list(structured.get("plan"), fallback=text)
            structured["risks"] = self._normalize_brain_router_list(structured.get("risks"))
            structured["missing_evidence"] = self._normalize_brain_router_list(structured.get("missing_evidence"))
            structured["recommended_next_lane"] = str(
                structured.get("recommended_next_lane") or "review_light"
            ).strip() or "review_light"
            structured["acceptance_checklist"] = self._normalize_brain_router_list(
                structured.get("acceptance_checklist")
            )
            normalized["structured_output_json"] = structured
            return normalized
        if capability_key == "reasoned_patch_review":
            structured["format"] = "review_packet"
            structured["recommendation"] = str(
                structured.get("recommendation") or structured.get("consensus") or text
            ).strip()
            structured["disagreements"] = self._normalize_brain_router_list(structured.get("disagreements"))
            structured["risks"] = self._normalize_brain_router_list(structured.get("risks"))
            structured["roles"] = self._normalize_brain_router_list(structured.get("roles")) or [
                "factuality",
                "adversarial",
                "completeness",
                "risk",
            ]
            structured["audit_scope"] = str(
                structured.get("audit_scope") or ("jury" if profile_name == "audit" else "review_light")
            ).strip() or ("jury" if profile_name == "audit" else "review_light")
            normalized["structured_output_json"] = structured
        return normalized

    def _normalize_brain_router_list(self, value: object, *, fallback: str = "") -> list[str]:
        if isinstance(value, list):
            values = [str(item or "").strip() for item in value if str(item or "").strip()]
            if values:
                return values
        if isinstance(value, tuple):
            values = [str(item or "").strip() for item in value if str(item or "").strip()]
            if values:
                return values
        text = str(value or "").strip()
        if text:
            return [text]
        fallback_text = str(fallback or "").strip()
        if fallback_text:
            return [fallback_text]
        return []

    @property
    def _browseract_live_extract(self):
        return self._browseract_module.live_extract

    @_browseract_live_extract.setter
    def _browseract_live_extract(self, handler) -> None:
        self._browseract_module.live_extract = handler

    @property
    def _browseract_chatplayground_audit(self):
        return self._browseract_module.chatplayground_audit

    @_browseract_chatplayground_audit.setter
    def _browseract_chatplayground_audit(self, handler) -> None:
        self._browseract_module.chatplayground_audit = handler

    @property
    def _browseract_gemini_web_generate(self):
        return self._browseract_module.gemini_web_generate

    @_browseract_gemini_web_generate.setter
    def _browseract_gemini_web_generate(self, handler) -> None:
        self._browseract_module.gemini_web_generate = handler

    @property
    def _browseract_onemin_billing_usage(self):
        return self._browseract_module.onemin_billing_usage

    @_browseract_onemin_billing_usage.setter
    def _browseract_onemin_billing_usage(self, handler) -> None:
        self._browseract_module.onemin_billing_usage = handler

    @property
    def _browseract_onemin_member_reconciliation(self):
        return self._browseract_module.onemin_member_reconciliation

    @_browseract_onemin_member_reconciliation.setter
    def _browseract_onemin_member_reconciliation(self, handler) -> None:
        self._browseract_module.onemin_member_reconciliation = handler

    @property
    def _browseract_crezlo_property_tour(self):
        return self._browseract_module.crezlo_property_tour

    @_browseract_crezlo_property_tour.setter
    def _browseract_crezlo_property_tour(self, handler) -> None:
        self._browseract_module.crezlo_property_tour = handler

    @property
    def _browseract_ui_service_callbacks(self) -> dict[str, object]:
        return self._browseract_module.ui_service_callbacks
