"""Module for comparing client bill of materials (BOM) against vendor quotes.

Implements a four-tier matching waterfall:
1. Exact SKU matching (deterministic normalized string equality).
2. Part number keyword scan (regex boundary lookup in text fields).
3. Text description overlap (Jaccard similarity with spec conflict penalties).
4. LLM judge arbitration (pairwise evaluation of ambiguous items).
"""

import re
from typing import Any, Dict, List, Optional, Set, Tuple
from pydantic import BaseModel, Field

from app.clients.base import BaseLLMClient
from app.core.exceptions import LLMClientError, MatchingError, MissingAnchorError
from app.core.logger import setup_logger
from app.schemas.comparison_schema import (
    ClientBOMComparisonRow,
    MatchStage,
    MatchVerdict,
    MultiVendorComparisonReport,
    UnsolicitedVendorItem,
    VendorItemOffer,
)
from app.schemas.page_extraction_schema import CanonicalItem, DocumentReconciliation

logger = setup_logger()

class JudgeVerdict(BaseModel):
    """Schema for Stage 4 LLM judge responses."""

    is_match: bool = Field(
        ...,
        description="True if the quoted item satisfies the requested item.",
    )
    verdict: MatchVerdict = Field(
        ...,
        description="Rating: IDENTICAL, COMPATIBLE_SUBSTITUTE, DIFFERENT_SPEC, or MISMATCH.",
    )
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Confidence score between 0.0 and 1.0.",
    )
    differences: List[str] = Field(
        default_factory=list,
        description="List of detected differences in specifications or terms.",
    )
    reasoning: str = Field(
        ...,
        description="Brief technical explanation justifying the verdict.",
    )
    
class QuoteComparator:
    """Compares customer BOM requirements against vendor quotes."""

    IGNORED_SKUS: Set[str] = {
        "ITEM", "ITEMS", "LINE", "ROW", "PART", "NA", "NONE", "NULL",
        "TBD", "SERVER", "SWITCH", "ROUTER", "TRANSCEIVER", "CABLE", "HARDWARE"
    }

    STOP_WORDS: Set[str] = {
        "a", "an", "the", "and", "or", "in", "on", "at", "to", "for", "with",
        "by", "of", "from", "is", "are", "per", "ea", "nos", "qty", "set"
    }

    SPEC_PATTERNS = {
        "length": re.compile(
            r"(\b\d+(?:\.\d+)?\s*(?:m(?:eter)?|ft|feet)\b)",
            re.IGNORECASE,
        ),
        "speed": re.compile(
            r"(\b(?:1000base-[a-z0-9]+|10gbase-[a-z0-9]+|100g|400g|800g|10g|1g|25g|40g)\b)",
            re.IGNORECASE,
        ),
        "form_factor": re.compile(
            r"(\b(?:qsfp-dd|qsfp28|qsfp\+|sfp\+|sfp28|sfp|rj45|dac)\b)",
            re.IGNORECASE,
        ),
    }
    
    @classmethod
    def clean_sku(cls, raw_sku: Optional[str]) -> Optional[str]:
        """Normalizes an SKU string for exact comparison.

        Strips whitespace, converts to uppercase, removes delimiters and punctuation,
        and excludes row numbers or generic placeholder words.

        Args:
            raw_sku: The raw SKU or part number string.

        Returns:
            The normalized alphanumeric SKU, or None if invalid or generic.
        """
        if not raw_sku:
            return None

        cleaned = raw_sku.strip().upper()
        if not cleaned:
            return None

        normalized = re.sub(r"[\s\-_=\./\\#:]+", "", cleaned)
        if len(normalized) < 3 or normalized.isdigit() or normalized in cls.IGNORED_SKUS:
            return None

        return normalized
    
    @classmethod
    def match_exact_sku(
        cls,
        target_sku: Optional[str],
        vendor_sku_map: Dict[str, Tuple[int, CanonicalItem]],
        used_indices: Set[int],
    ) -> Optional[Tuple[int, CanonicalItem, float, MatchStage, MatchVerdict, List[str]]]:
        """Matches a target SKU against indexed vendor items (Stage 1).

        Args:
            target_sku: The SKU requested by the client.
            vendor_sku_map: Map of normalized SKU to tuple of (index, item).
            used_indices: Set of vendor item indices already matched.

        Returns:
            Tuple of (index, item, confidence, stage, verdict, differences) if matched,
            otherwise None.
        """
        norm_sku = cls.clean_sku(target_sku)
        if not norm_sku:
            return None

        if norm_sku in vendor_sku_map:
            idx, item = vendor_sku_map[norm_sku]
            if idx not in used_indices:
                logger.info("Stage 1 (Exact SKU) match: %s -> %s", target_sku, item.product_id)
                return idx, item, 1.0, MatchStage.EXACT_SKU, MatchVerdict.IDENTICAL, []

        return None
    
    @classmethod
    def match_sku_in_text(
        cls,
        target_sku: Optional[str],
        vendor_items: List[CanonicalItem],
        used_indices: Set[int],
    ) -> Optional[Tuple[int, CanonicalItem, float, MatchStage, MatchVerdict, List[str]]]:
        """Scans vendor text fields for the target SKU (Stage 2).

        Args:
            target_sku: The SKU requested by the client.
            vendor_items: Full list of items quoted by the vendor.
            used_indices: Set of vendor item indices already matched.

        Returns:
            Tuple of (index, item, confidence, stage, verdict, differences) if matched,
            otherwise None.
        """
        if not target_sku or len(target_sku.strip()) < 3:
            return None

        clean_target = target_sku.strip()
        pattern = re.compile(
            rf"(?<![A-Za-z0-9]){re.escape(clean_target)}(?![A-Za-z0-9])",
            re.IGNORECASE,
        )

        for idx, item in enumerate(vendor_items):
            if idx in used_indices:
                continue

            search_blob = f"{item.product_name or ''} {item.description_and_specs or ''} {item.raw_text or ''}"
            if pattern.search(search_blob):
                logger.info(f"Stage 2 (SKU in text) match: {clean_target} found in vendor item {idx}")
                return idx, item, 0.95, MatchStage.TOKEN_REGEX, MatchVerdict.IDENTICAL, []

        return None
    
    @classmethod
    def _get_tokens(cls, text: str) -> Set[str]:
        """Extracts lowercase word tokens, filtering out stop words.

        Args:
            text: Input string to tokenize.

        Returns:
            Set of cleaned token strings.
        """
        tokens = re.findall(r"[A-Za-z0-9]+", text.lower())
        return {t for t in tokens if len(t) > 1 and t not in cls.STOP_WORDS}
    
    @classmethod
    def _get_spec_attributes(cls, text: str) -> Dict[str, Set[str]]:
        """Extracts networking spec keywords such as length, speed, and form factor.

        Args:
            text: Input string containing technical specs.

        Returns:
            Dictionary mapping spec category names to sets of found normalized values.
        """
        specs: Dict[str, Set[str]] = {}
        for category, pattern in cls.SPEC_PATTERNS.items():
            matches = pattern.findall(text)
            specs[category] = {re.sub(r"\s+", "", m.lower()) for m in matches}
        return specs
    
    @classmethod
    def match_description(
        cls,
        target_desc: str,
        vendor_items: List[CanonicalItem],
        used_indices: Set[int],
        threshold: float = 0.55,
    ) -> Optional[Tuple[int, CanonicalItem, float, MatchStage, MatchVerdict, List[str]]]:
        """Matches description text using token overlap and spec checking (Stage 3).

        Args:
            target_desc: Description string requested by the client.
            vendor_items: Full list of items quoted by the vendor.
            used_indices: Set of vendor item indices already matched.
            threshold: Minimum adjusted similarity score to qualify as a match.

        Returns:
            Tuple of (index, item, confidence, stage, verdict, differences) if matched,
            otherwise None.
        """
        target_tokens = cls._get_tokens(target_desc)
        if not target_tokens:
            return None

        target_specs = cls._get_spec_attributes(target_desc)
        best_score = 0.0
        best_item: Optional[Tuple[int, CanonicalItem]] = None
        best_diffs: List[str] = []

        for idx, item in enumerate(vendor_items):
            if idx in used_indices:
                continue

            vendor_blob = f"{item.product_name or ''} {item.description_and_specs or ''} {item.raw_text or ''}"
            vendor_tokens = cls._get_tokens(vendor_blob)
            if not vendor_tokens:
                continue

            intersection = target_tokens.intersection(vendor_tokens)
            union = target_tokens.union(vendor_tokens)
            score = len(intersection) / len(union) if union else 0.0

            # Penalize conflicting hardware attributes (e.g., 3m vs 5m)
            vendor_specs = cls._get_spec_attributes(vendor_blob)
            diffs: List[str] = []
            penalty = 0.0

            for cat in ["length", "speed", "form_factor"]:
                t_val = target_specs.get(cat)
                v_val = vendor_specs.get(cat)
                if t_val and v_val and not t_val.intersection(v_val):
                    diffs.append(f"Mismatched {cat}: Requested {t_val} vs Quoted {v_val}")
                    penalty += 0.35

            adjusted_score = max(0.0, score - penalty)

            if adjusted_score > best_score:
                best_score = adjusted_score
                best_item = (idx, item)
                best_diffs = diffs

        if best_item and best_score >= threshold:
            confidence = round(min(0.92, 0.65 + (best_score * 0.25)), 2)
            verdict = (
                MatchVerdict.IDENTICAL
                if confidence >= 0.88 and not best_diffs
                else MatchVerdict.COMPATIBLE_SUBSTITUTE
            )
            logger.info("Stage 3 (Description) match: score=%.2f, confidence=%.2f", best_score, confidence)
            return best_item[0], best_item[1], confidence, MatchStage.SEMANTIC_BLOB, verdict, best_diffs

        return None
    
    @classmethod
    def match_with_llm(
        cls,
        target_desc: str,
        vendor_items: List[CanonicalItem],
        used_indices: Set[int],
        llm_client: BaseLLMClient,
    ) -> Optional[Tuple[int, CanonicalItem, float, MatchStage, MatchVerdict, List[str]]]:
        """Arbitrates ambiguous items using an LLM judge (Stage 4).

        Args:
            target_desc: Description string requested by the client.
            vendor_items: Full list of items quoted by the vendor.
            used_indices: Set of vendor item indices already matched.
            llm_client: Client implementation conforming to BaseLLMClient.

        Returns:
            Tuple of (index, item, confidence, stage, verdict, differences) if matched,
            otherwise None.
        """
        target_tokens = cls._get_tokens(target_desc)
        scored_candidates: List[Tuple[int, int, CanonicalItem]] = []

        for idx, item in enumerate(vendor_items):
            if idx in used_indices:
                continue
            vendor_blob = f"{item.product_name or ''} {item.description_and_specs or ''}"
            overlap = len(target_tokens.intersection(cls._get_tokens(vendor_blob)))
            scored_candidates.append((overlap, idx, item))

        scored_candidates.sort(key=lambda x: x[0], reverse=True)
        top_candidates = scored_candidates[:3]

        if not top_candidates or top_candidates[0][0] == 0:
            return None

        system_prompt = (
            "You are an expert procurement auditor. Compare the requested product specification "
            "against a candidate quotation item. Determine if the candidate is an exact match, "
            "a compatible substitute, or a mismatch. Output strict JSON matching the schema."
        )

        for _, idx, candidate in top_candidates:
            user_content = (
                f"CLIENT REQUIREMENT:\n\"{target_desc}\"\n\n"
                f"CANDIDATE VENDOR ITEM:\n"
                f"- SKU: {candidate.product_id or 'None'}\n"
                f"- Title: {candidate.product_name or 'None'}\n"
                f"- Specs: {candidate.description_and_specs or candidate.raw_text or 'None'}\n\n"
                "Evaluate compatibility."
            )

            try:
                result: JudgeVerdict = llm_client.generate_response(
                    system_prompt=system_prompt,
                    user_content=user_content,
                    response_schema=JudgeVerdict,
                    temperature=0.0,
                )

                if result.is_match and result.verdict in (
                    MatchVerdict.IDENTICAL,
                    MatchVerdict.COMPATIBLE_SUBSTITUTE,
                ):
                    logger.info("Stage 4 (LLM Judge) match: %s (confidence=%.2f)", result.verdict.value, result.confidence)
                    return idx, candidate, result.confidence, MatchStage.LLM_JUDGE, result.verdict, result.differences

            except LLMClientError as e:
                logger.warning("Stage 4 LLM Judge call failed for item %s: %s", candidate.product_id, e)
                continue
            except Exception as e:
                logger.error("Unexpected error in Stage 4 LLM Judge: %s", e)
                continue

        return None

    @classmethod
    def match_item(
        cls,
        target_sku: Optional[str],
        target_desc: str,
        vendor_items: List[CanonicalItem],
        vendor_sku_map: Dict[str, Tuple[int, CanonicalItem]],
        used_indices: Set[int],
        llm_client: Optional[BaseLLMClient] = None,
    ) -> Optional[Tuple[int, CanonicalItem, float, MatchStage, MatchVerdict, List[str]]]:
        """Runs the four-tier waterfall sequentially for a single item requirement.

        Args:
            target_sku: SKU requested by client (can be None).
            target_desc: Description requested by client.
            vendor_items: Full list of items quoted by the vendor.
            vendor_sku_map: Map of normalized SKU to tuple of (index, item).
            used_indices: Set of vendor item indices already matched.
            llm_client: Optional LLM client instance for Stage 4 fallback.

        Returns:
            Tuple of match results if any tier succeeds, otherwise None.
        """
        # Tier 1 & 2: SKU matching (only if SKU was provided)
        if target_sku:
            res = cls.match_exact_sku(target_sku, vendor_sku_map, used_indices)
            if res:
                return res

            res = cls.match_sku_in_text(target_sku, vendor_items, used_indices)
            if res:
                return res

        # Tier 3: Description overlap
        res = cls.match_description(target_desc, vendor_items, used_indices)
        if res:
            return res

        # Tier 4: LLM Judge fallback
        if llm_client is not None:
            res = cls.match_with_llm(target_desc, vendor_items, used_indices, llm_client)
            if res:
                return res

        return None

    @classmethod
    def compare(
        cls,
        client_bom: List[Dict[str, Any]],
        vendor_quotes: List[DocumentReconciliation],
        target_currency: str = "USD",
        client_name: str = "Client Project",
        llm_client: Optional[BaseLLMClient] = None,
    ) -> MultiVendorComparisonReport:
        """Compares a client BOM against multiple vendor quotes.

        Matches items, compares prices, flags missing items per vendor,
        identifies extra unrequested items, and calculates potential cost savings.

        Args:
            client_bom: List of client item dictionaries (keys: sku, description, quantity).
            vendor_quotes: List of DocumentReconciliation instances from extracted quotes.
            target_currency: 3-letter currency code for comparison display.
            client_name: Project or customer name for report metadata.
            llm_client: Optional LLM client for Stage 4 fallback.

        Returns:
            A MultiVendorComparisonReport instance containing the comparison matrix.

        Raises:
            MissingAnchorError: If client_bom is empty.
            MatchingError: If vendor_quotes is empty.
        """
        if not client_bom:
            raise MissingAnchorError("Client BOM contains no items to compare against.")

        if not vendor_quotes:
            raise MatchingError("At least one vendor quote is required for comparison.")

        doc_metadata: Dict[str, str] = {}
        doc_id_to_quote: Dict[str, DocumentReconciliation] = {}
        all_doc_ids: List[str] = []

        for i, q in enumerate(vendor_quotes, start=1):
            doc_id = getattr(q, "doc_id", None) or f"doc_{i}"
            vendor_label = q.vendor_name or f"Vendor_{i}"
            doc_metadata[doc_id] = vendor_label
            doc_id_to_quote[doc_id] = q
            all_doc_ids.append(doc_id)

        used_items: Dict[str, Set[int]] = {d_id: set() for d_id in all_doc_ids}

        # Index normalized SKUs by doc_id for Stage 1 lookups
        sku_maps: Dict[str, Dict[str, Tuple[int, CanonicalItem]]] = {}
        for d_id in all_doc_ids:
            quote = doc_id_to_quote[d_id]
            sku_map: Dict[str, Tuple[int, CanonicalItem]] = {}
            for idx, item in enumerate(quote.items):
                clean = cls.clean_sku(item.product_id)
                if clean:
                    sku_map[clean] = (idx, item)
            sku_maps[d_id] = sku_map

        comparison_rows: List[ClientBOMComparisonRow] = []

        # Match each BOM requirement against all vendors
        for row_idx, bom_item in enumerate(client_bom, start=1):
            req_sku = bom_item.get("product_id") or bom_item.get("sku")
            req_desc = bom_item.get("description") or bom_item.get("description_and_specs") or ""
            req_qty = float(bom_item.get("quantity", 1.0))
            req_uom = bom_item.get("unit_of_measure")

            vendor_offers: Dict[str, Optional[VendorItemOffer]] = {}
            missing_doc_ids: List[str] = []

            for d_id in all_doc_ids:
                quote = doc_id_to_quote[d_id]
                used = used_items[d_id]
                sku_map = sku_maps[d_id]
                vendor_display_name = doc_metadata[d_id]

                try:
                    match = cls.match_item(
                        target_sku=req_sku,
                        target_desc=req_desc,
                        vendor_items=quote.items,
                        vendor_sku_map=sku_map,
                        used_indices=used,
                        llm_client=llm_client,
                    )
                except Exception as e:
                    logger.error("Error matching row %d for doc_id '%s': %s", row_idx, d_id, e)
                    match = None

                if match:
                    item_idx, item, confidence, stage, verdict, diffs = match
                    used.add(item_idx)

                    discount_mult = 1.0 - (item.discount_percent / 100.0)
                    total_price = round(req_qty * item.unit_price * discount_mult, 2)

                    vendor_offers[d_id] = VendorItemOffer(
                        doc_id=d_id,
                        vendor_name=vendor_display_name,
                        quote_number=quote.quote_number,
                        matched_product_id=item.product_id,
                        matched_product_name=item.product_name,
                        matched_description=item.description_and_specs,
                        unit_price=item.unit_price,
                        discount_percent=item.discount_percent,
                        total_price=total_price,
                        currency=quote.currency or target_currency,
                        match_stage=stage,
                        verdict=verdict,
                        confidence_score=confidence,
                        spec_discrepancies=diffs,
                    )
                else:
                    vendor_offers[d_id] = None
                    missing_doc_ids.append(d_id)

            # Price comparison for this row
            valid_bids = [
                (d_id, offer.unit_price)
                for d_id, offer in vendor_offers.items()
                if offer is not None and offer.unit_price > 0
            ]
            lowest_unit_price: Optional[float] = None
            recommended_doc_id: Optional[str] = None
            recommended_vendor_name: Optional[str] = None
            unit_savings: Optional[float] = None
            total_savings: Optional[float] = None

            if valid_bids:
                valid_bids.sort(key=lambda x: x[1])
                recommended_doc_id, lowest_unit_price = valid_bids[0]
                recommended_vendor_name = doc_metadata.get(recommended_doc_id, "Unknown Vendor")
                if len(valid_bids) > 1:
                    unit_savings = round(valid_bids[1][1] - lowest_unit_price, 2)
                    total_savings = round(unit_savings * req_qty, 2)
                else:
                    unit_savings = 0.0
                    total_savings = 0.0

            comparison_rows.append(
                ClientBOMComparisonRow(
                    line_number=row_idx,
                    requested_sku=req_sku,
                    requested_description=req_desc,
                    requested_quantity=req_qty,
                    unit_of_measure=req_uom,
                    vendor_offers=vendor_offers,
                    missing_from_doc_ids=missing_doc_ids,
                    lowest_unit_price=lowest_unit_price,
                    recommended_doc_id=recommended_doc_id,
                    recommended_vendor_name=recommended_vendor_name,
                    potential_unit_savings=unit_savings,
                    potential_total_savings=total_savings,
                )
            )

        # Identify extra items quoted by vendors but not present in the BOM
        unsolicited_by_doc_id: Dict[str, List[UnsolicitedVendorItem]] = {}
        unsolicited_spend: Dict[str, float] = {}

        for d_id in all_doc_ids:
            quote = doc_id_to_quote[d_id]
            used = used_items[d_id]
            vendor_display_name = doc_metadata[d_id]
            extras: List[UnsolicitedVendorItem] = []
            extra_total = 0.0

            for idx, item in enumerate(quote.items):
                if idx not in used and item.total_price > 0:
                    extras.append(
                        UnsolicitedVendorItem(
                            doc_id=d_id,
                            vendor_name=vendor_display_name,
                            quote_number=quote.quote_number,
                            product_id=item.product_id,
                            product_name=item.product_name,
                            description_and_specs=item.description_and_specs,
                            quantity=item.quantity,
                            unit_price=item.unit_price,
                            total_price=item.total_price,
                        )
                    )
                    extra_total += item.total_price

            unsolicited_by_doc_id[d_id] = extras
            unsolicited_spend[d_id] = round(extra_total, 2)

        # Calculate high-level summary KPIs
        total_requested = len(comparison_rows)
        fully_matched = sum(1 for r in comparison_rows if not r.missing_from_doc_ids)
        unmatched = sum(1 for r in comparison_rows if len(r.missing_from_doc_ids) == len(all_doc_ids))
        partially_matched = total_requested - fully_matched - unmatched

        total_spend: Dict[str, float] = {}
        compliance_rates: Dict[str, float] = {}

        for d_id in all_doc_ids:
            spend_sum = sum(
                r.vendor_offers[d_id].total_price
                for r in comparison_rows
                if r.vendor_offers.get(d_id) is not None
            )
            total_spend[d_id] = round(spend_sum, 2)
            matched_count = sum(1 for r in comparison_rows if r.vendor_offers.get(d_id) is not None)
            compliance_rates[d_id] = (
                round((matched_count / total_requested) * 100.0, 1)
                if total_requested else 0.0
            )

        optimal_hybrid = round(
            sum(
                r.lowest_unit_price * r.requested_quantity
                for r in comparison_rows
                if r.lowest_unit_price is not None
            ),
            2,
        )

        highest_spend = max(total_spend.values()) if total_spend else 0.0
        max_savings = round(highest_spend - optimal_hybrid, 2) if highest_spend > optimal_hybrid else 0.0

        # Rank vendors: best catalog compliance first, then lowest total cost
        ranked_doc_ids = sorted(
            all_doc_ids,
            key=lambda d: (-compliance_rates[d], total_spend[d]),
        )
        best_doc_id = ranked_doc_ids[0] if ranked_doc_ids else None
        best_vendor_name = doc_metadata.get(best_doc_id) if best_doc_id else None

        logger.info(
            "Comparison complete: %d items analyzed. Optimal spend: %s %.2f. Recommended: %s (%s)",
            total_requested,
            target_currency,
            optimal_hybrid,
            best_vendor_name,
            best_doc_id,
        )

        return MultiVendorComparisonReport(
            client_name=client_name,
            doc_metadata=doc_metadata,
            currency=target_currency,
            rows=comparison_rows,
            unsolicited_items_by_doc_id=unsolicited_by_doc_id,
            total_requested_items=total_requested,
            fully_matched_items=fully_matched,
            partially_matched_items=partially_matched,
            unmatched_items=unmatched,
            doc_compliance_rates=compliance_rates,
            total_spend_by_doc_id=total_spend,
            unsolicited_spend_by_doc_id=unsolicited_spend,
            optimal_hybrid_spend=optimal_hybrid,
            max_potential_savings=max_savings,
            overall_recommended_doc_id=best_doc_id,
            overall_recommended_vendor_name=best_vendor_name,
        )