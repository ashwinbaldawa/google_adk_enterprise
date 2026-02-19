"""
OpenTelemetry + Phoenix observability setup.

Call setup_observability() BEFORE importing ADK modules.
Swap Phoenix for Dynatrace/Datadog by changing the OTLP endpoint.
"""

import logging

logger = logging.getLogger(__name__)


def setup_observability() -> bool:
    """Initialize Phoenix and OpenTelemetry instrumentation.

    Returns True if observability is active, False otherwise.
    """
    try:
        import phoenix as px

        px.launch_app()
        logger.info("Phoenix UI: http://localhost:6006")

        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

        exporter = OTLPSpanExporter(endpoint="http://localhost:4317", insecure=True)
        provider = TracerProvider()
        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)

        from openinference.instrumentation.google_adk import GoogleADKInstrumentor
        GoogleADKInstrumentor().instrument()

        print("🔭 Phoenix UI: http://localhost:6006")
        print("✅ OpenTelemetry + ADK instrumentation active")
        return True

    except ImportError as e:
        print(f"⚠️  Observability not available: {e}")
        print("   Install: pip install arize-phoenix opentelemetry-sdk opentelemetry-exporter-otlp-proto-grpc openinference-instrumentation-google-adk")
        return False
    except Exception as e:
        print(f"⚠️  Observability setup failed: {e}")
        return False
