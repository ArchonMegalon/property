# PropertyQuarry Failure UX

Failures are normal in PropertyQuarry: providers change pages, PDF renderers fail, 3D tour providers may be unavailable, MagicFit can be blocked, and external tools may be disabled.

Every customer-visible failure must include:

```text
human message
operator detail
retry action
fallback action
receipt
```

## Examples

| Bad | Good |
| --- | --- |
| `premium_dossier_render_failed` | The premium PDF did not pass quality checks. Retry local rendering or send the review without the PDF. |
| `tour_control_3dvista_export_missing` | 3DVista export is not available yet. Retry export or use the Matterport tour for this property. |
| `provider_timeout` | This provider did not respond in time. Keep the search running and show already ranked matches. |
| `magicfit_blocked` | The fly-through renderer is unavailable. Queue a retry with another approved photorealistic video provider. |

