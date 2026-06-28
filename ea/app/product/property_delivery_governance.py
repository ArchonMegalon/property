from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class PropertyDeliveryChannelPolicy:
    channel_key: str
    label: str
    verified_destination_required: bool
    opt_in_required: bool
    stop_start_supported: bool
    quiet_hours_supported: bool
    receipt_required: bool
    suppression_required: bool
    customer_control_label: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


PROPERTY_DELIVERY_CHANNEL_POLICIES: tuple[PropertyDeliveryChannelPolicy, ...] = (
    PropertyDeliveryChannelPolicy(
        channel_key="email",
        label="Email",
        verified_destination_required=True,
        opt_in_required=True,
        stop_start_supported=False,
        quiet_hours_supported=True,
        receipt_required=True,
        suppression_required=True,
        customer_control_label="Email preferences",
    ),
    PropertyDeliveryChannelPolicy(
        channel_key="telegram",
        label="Telegram",
        verified_destination_required=True,
        opt_in_required=True,
        stop_start_supported=False,
        quiet_hours_supported=True,
        receipt_required=True,
        suppression_required=False,
        customer_control_label="Telegram binding",
    ),
    PropertyDeliveryChannelPolicy(
        channel_key="whatsapp",
        label="WhatsApp",
        verified_destination_required=True,
        opt_in_required=True,
        stop_start_supported=True,
        quiet_hours_supported=True,
        receipt_required=True,
        suppression_required=True,
        customer_control_label="WhatsApp opt-in",
    ),
)

PROPERTY_DELIVERY_CHANNEL_INDEX = {policy.channel_key: policy for policy in PROPERTY_DELIVERY_CHANNEL_POLICIES}


def property_delivery_channel_policy(channel_key: object) -> PropertyDeliveryChannelPolicy | None:
    return PROPERTY_DELIVERY_CHANNEL_INDEX.get(str(channel_key or "").strip().lower())


def property_delivery_governance_rows(selected_channels: object) -> list[dict[str, object]]:
    if isinstance(selected_channels, (list, tuple, set)):
        selected = {str(channel or "").strip().lower() for channel in selected_channels if str(channel or "").strip()}
    else:
        selected = {part.strip().lower() for part in str(selected_channels or "").replace(";", ",").split(",") if part.strip()}
    rows: list[dict[str, object]] = []
    for policy in PROPERTY_DELIVERY_CHANNEL_POLICIES:
        enabled = policy.channel_key in selected
        controls = ["address confirmed", "delivery history"]
        if policy.opt_in_required:
            controls.append("opt-in")
        if policy.stop_start_supported:
            controls.append("pause or resume")
        if policy.quiet_hours_supported:
            controls.append("quiet hours")
        if policy.suppression_required:
            controls.append("duplicate guard")
        rows.append(
            {
                "channel_key": policy.channel_key,
                "title": policy.label,
                "detail": ", ".join(controls),
                "tag": "On" if enabled else "Off",
                "enabled": enabled,
                "customer_control_label": policy.customer_control_label,
            }
        )
    return rows
