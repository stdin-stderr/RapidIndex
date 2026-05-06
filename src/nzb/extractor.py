"""NZB file extractor.

Parses assembled NZB XML to extract individual files with their metadata.
"""

import logging
import xml.etree.ElementTree as ET
from typing import TypedDict

log = logging.getLogger(__name__)


class FileInfo(TypedDict):
    filename: str
    file_size_bytes: int
    segment_ids: list[str]
    file_index: int


def extract_files_from_nzb(nzb_xml: bytes) -> list[FileInfo]:
    """Parse NZB XML and extract file metadata.

    Args:
        nzb_xml: Raw NZB XML as bytes (UTF-8 encoded)

    Returns:
        List of files with filename, size, segment IDs, and index
    """
    if not nzb_xml:
        return []

    try:
        root = ET.fromstring(nzb_xml)
    except ET.ParseError as e:
        log.error("Failed to parse NZB XML: %s", e)
        return []

    files: list[FileInfo] = []

    # NZB namespace (usually prefixed as nzb in XML)
    ns = {"nzb": "http://www.newzbin.com/DTD/2003/nzb"}

    # Try with namespace first, fall back to no namespace
    file_elements = root.findall(".//nzb:file", ns)
    if not file_elements:
        file_elements = root.findall(".//file")

    for file_index, file_elem in enumerate(file_elements):
        filename = file_elem.get("subject")
        if not filename:
            continue

        # Collect segment metadata
        segment_elements = file_elem.findall(".//nzb:segment", ns)
        if not segment_elements:
            segment_elements = file_elem.findall(".//segment")

        segment_ids: list[str] = []
        total_size: int = 0

        for segment_elem in segment_elements:
            segment_id = segment_elem.text
            if segment_id:
                segment_ids.append(segment_id.strip())

            # Get segment size (bytes attribute)
            size_str = segment_elem.get("bytes")
            if size_str:
                try:
                    total_size += int(size_str)
                except ValueError:
                    pass

        if segment_ids:
            files.append(
                FileInfo(
                    filename=filename,
                    file_size_bytes=total_size,
                    segment_ids=segment_ids,
                    file_index=file_index,
                )
            )

    log.debug("Extracted %d files from NZB", len(files))
    return files
