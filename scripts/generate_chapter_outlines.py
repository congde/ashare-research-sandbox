"""Compatibility entry point for generating the current 35 course chapters."""

from rewrite_quant_course import CHAPTERS, main

__all__ = ["CHAPTERS", "main"]


if __name__ == "__main__":
    main()
