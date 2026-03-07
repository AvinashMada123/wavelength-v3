"""Build Plivo XML responses for call control."""

from xml.etree.ElementTree import Element, SubElement, tostring


def build_stream_xml(
    websocket_url: str,
    bidirectional: bool = True,
    content_type: str = "audio/x-l16;rate=16000",
    stream_timeout: int = 3600,
    keep_call_alive: bool = True,
    recording_callback_url: str | None = None,
) -> str:
    """Build Plivo <Response><Record><Stream> XML for WebSocket audio streaming."""
    response = Element("Response")

    # Record the entire call server-side (background, non-blocking)
    if recording_callback_url:
        record = SubElement(response, "Record")
        record.set("recordSession", "true")
        record.set("redirect", "false")
        record.set("fileFormat", "mp3")
        record.set("callbackUrl", recording_callback_url)
        record.set("callbackMethod", "POST")

    stream = SubElement(response, "Stream")
    stream.set("bidirectional", str(bidirectional).lower())
    stream.set("contentType", content_type)
    stream.set("streamTimeout", str(stream_timeout))
    stream.set("keepCallAlive", str(keep_call_alive).lower())
    stream.text = websocket_url
    return tostring(response, encoding="unicode", xml_declaration=False)


def build_hangup_xml() -> str:
    """Build Plivo <Response><Hangup/> XML."""
    response = Element("Response")
    SubElement(response, "Hangup")
    return tostring(response, encoding="unicode", xml_declaration=False)
