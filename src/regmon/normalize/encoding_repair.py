"""Encoding repair for mojibake and character encoding issues (Phase 2b)."""

from __future__ import annotations

import logging
from typing import TypedDict

import chardet
import ftfy

logger = logging.getLogger(__name__)


class RepairInfo(TypedDict):
    encoding_fixed: bool
    original_encoding: str | None
    ftfy_applied: bool


class EncodingRepair:
    """Repairs text encoding issues using ftfy with chardet fallback."""

    def __init__(self, enable_ftfy: bool = True, enable_chardet: bool = True) -> None:
        """
        Initialize encoding repair.

        Args:
            enable_ftfy: Whether to apply ftfy.fix_text (default: True).
            enable_chardet: Whether to use chardet for encoding detection (default: True).
        """
        self.enable_ftfy = enable_ftfy
        self.enable_chardet = enable_chardet

    def repair(self, text: str) -> tuple[str, RepairInfo]:
        """
        Repair text encoding issues.

        Args:
            text: Input text that may have encoding problems.

        Returns:
            Tuple of (clean_text, repair_info) where repair_info contains:
            - encoding_fixed: bool - whether any encoding fix was applied
            - original_encoding: str | None - detected original encoding
            - ftfy_applied: bool - whether ftfy was applied
        """
        if not text or not text.strip():
            info: RepairInfo = {
                "encoding_fixed": False,
                "original_encoding": None,
                "ftfy_applied": False,
            }
            return text, info

        repair_info: RepairInfo = {
            "encoding_fixed": False,
            "original_encoding": None,
            "ftfy_applied": False,
        }

        # First, try to detect if text has been misdecoded
        # Common mojibake patterns that ftfy can fix
        if self.enable_ftfy:
            try:
                fixed = ftfy.fix_text(text)
                if fixed != text:
                    logger.debug("ftfy fixed text: %s... -> %s...", text[:50], fixed[:50])
                    text = fixed
                    repair_info["ftfy_applied"] = True
                    repair_info["encoding_fixed"] = True
            except Exception as e:
                logger.debug("ftfy failed: %s", e)

        # If text still seems garbled, try chardet-based approach
        if self.enable_chardet and repair_info["encoding_fixed"] is False:
            try:
                # Check if we can detect a different encoding
                # Encode back to bytes and try to detect
                text_bytes = text.encode("utf-8", errors="ignore")
                if text_bytes:
                    detected = chardet.detect(text_bytes)
                    encoding_val: str | None = detected.get("encoding") if detected else None
                    conf_val: float = detected.get("confidence", 0) if detected else 0
                    if encoding_val and conf_val > 0.7:
                        encoding = encoding_val.lower()
                        if encoding not in ("utf-8", "ascii"):
                            repair_info["original_encoding"] = encoding
                            logger.debug(
                                "chardet detected encoding: %s (confidence: %.2f)",
                                encoding,
                                detected.get("confidence", 0),
                            )
            except Exception as e:
                logger.debug("chardet detection failed: %s", e)

        # Final ftfy pass on the result
        if self.enable_ftfy and repair_info["ftfy_applied"]:
            try:
                final_fixed = ftfy.fix_text(text)
                if final_fixed != text:
                    text = final_fixed
            except Exception as e:
                logger.debug("Final ftfy pass failed: %s", e)

        return text, repair_info


def repair_encoding(text: str) -> tuple[str, RepairInfo]:
    """Convenience function using default EncodingRepair instance."""
    repairer = EncodingRepair()
    return repairer.repair(text)


__all__ = ["EncodingRepair", "repair_encoding"]
