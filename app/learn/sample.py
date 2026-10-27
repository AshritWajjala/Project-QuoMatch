import email
from email import policy
from pathlib import Path
import re
from typing import Tuple
from bs4 import BeautifulSoup


class EmailIngestionService:
  """Parses .eml RFC 822 files and strips historical reply chains."""

  REPLY_REGEX_PATTERNS = [
      r"(?m)^_{5,}",  # Horizontal rule / underscores
      r"(?m)^-{5,}\s*Original Message\s*-{5,}",  # Outlook original message
      r"(?m)^On\s+.+?wrote:\s*$",  # Gmail / Apple Mail 'On ... wrote:'
      r"(?m)^From:\s+.+?\nSent:\s+",  # Standard Outlook headers
      r"(?m)^From:\s+.+?\nDate:\s+",  # Standard RFC headers
  ]

  ALLOWED_TAGS = {
      "table",
      "thead",
      "tbody",
      "tr",
      "th",
      "td",
      "p",
      "ul",
      "ol",
      "li",
      "span",
      "div",
      "br",
      "b",
      "strong",
      "i",
      "em",
  }

  @classmethod
  def extract_active_message_content(cls, eml_path: Path) -> str:
    """Ingests an email file, strips previous historical reply chains, and returns cleaned active message content.

        Args:
            eml_path (Path): Path to the .eml file to process.

        Returns:
            str: Cleaned HTML or plain text representing only the active message.
    """
    raw_content, is_html = cls._load_payload(eml_path)

    if is_html:
      return cls._clean_html_content(raw_content)
    return cls._clean_plain_text_content(raw_content)

  @classmethod
  def _load_payload(cls, eml_path: Path) -> Tuple[str, bool]:
    """Loads and extracts the raw message body from an RFC 822 .eml file, prioritizing HTML over plain text.

        Args:
            eml_path (Path): Path to the .eml file on disk.

        Returns:
            Tuple[str, bool]: A tuple containing the raw body content string and a boolean flag indicating if it is HTML (True) or plain text (False).
    """
    with open(eml_path, "rb") as f:
      msg = email.message_from_binary_file(f, policy=policy.default)

    html_part = msg.get_body(preferencelist=("html",))
    if html_part:
      return html_part.get_content(), True

    plain_part = msg.get_body(preferencelist=("plain",))
    if plain_part:
      return plain_part.get_content(), False

    raise ValueError(f"No text or HTML content found in {eml_path.name}")

  @classmethod
  def _clean_plain_text_content(cls, raw_text: str) -> str:
    """Truncates plain text content at the first occurrence of common quoted reply boundaries.

        Args:
            raw_text (str): Raw body text extracted from the email.

        Returns:
            str: Trimmed plain text with previous email conversation history removed.
    """
    cleaned = raw_text
    for pattern in cls.REPLY_REGEX_PATTERNS:
      parts = re.split(pattern, cleaned, maxsplit=1, flags=re.IGNORECASE)
      if len(parts) > 1:
        cleaned = parts[0]
    return cleaned.strip()

  @classmethod
  def _clean_html_content(cls, raw_html: str) -> str:
    """Parses HTML email markup, prunes vendor reply container DOM elements, and removes non-semantic styling tags.

        Args:
            raw_html (str): Raw HTML string from the email body.

        Returns:
            str: Normalized, sanitized HTML structure containing only the latest message content and tables.
    """
    soup = BeautifulSoup(raw_html, "html.parser")

    # 1. Remove non-content elements
    for element in soup(["script", "style", "head", "title", "meta", "img"]):
      element.decompose()

    # 2. Prune Gmail quoted blocks
    for div in soup.find_all(
        "div", class_=lambda c: c and ("gmail_quote" in c or "gmail_extra" in c)
    ):
      div.decompose()

    # 3. Prune Outlook reply containers
    for elem in soup.find_all(
        ["div", "p"], id=lambda i: i and "divRplyFwdMsg" in i
    ):
      for sibling in list(elem.find_next_siblings()):
        sibling.decompose()
      elem.decompose()

    # 4. Prune standard blockquotes
    for bq in soup.find_all("blockquote"):
      bq.decompose()

    # 5. Sanitize attributes (retain only structure to save LLM tokens)
    for tag in soup.find_all():
      if tag.name not in cls.ALLOWED_TAGS:
        tag.unwrap()
      else:
        tag.attrs = {}

    # Collapse empty whitespace while keeping table line breaks
    cleaned_html = str(soup)
    cleaned_html = re.sub(r"\n\s*\n", "\n", cleaned_html)
    return cleaned_html.strip()

  if __name__ == "__main__":
    eml_file_path = "'/Users/ashritw/Downloads/REQUIREMENT FOR _DELL (or) HP (or) LENOVO LAPTOP_.eml'"

    from app.clients.ollama_client import OllamaClient
    from app.core.config import get_settings

    settings = get_settings()

    remote_extraction_client = OllamaClient(model=settings.EXTRACTOR_MODEL, host_url=settings.HOME_PC_IP.get_secret_value())

    