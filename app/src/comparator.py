"""Multi-Vendor Quotation Comparison Engine."""

import re
from typing import Any, Dict, List, Optional, Set, Tuple
from app.clients.base import BaseLLMClient
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


class QuoteComparator:
    """Core arbitration engine for BOM vs. Multi-Vendor Quote comparisons."""

    IGNORED_SKUS = {"NA", "N/A", "NONE", "NULL", "-", "--", "ITEM"}

    SPEC_PATTERNS = {
        "length": re.compile(
            r"(\b\d+(?:\.\d+)?\s*(?:m(?:eter)?|ft|feet)\b)",
            re.IGNORECASE,
        ),
        "speed": re.compile(
            r"(\b(?:1000base-?[a-z0-9]*|10gbase-?[a-z0-9]*|100g|400g|800g|10g|1g|25g|40g)\b)",
            re.IGNORECASE,
        ),
        "form_factor": re.compile(
            r"(\b(?:qsfp-dd|qsfp28|qsfp\+|sfp\+|sfp28|sfp|rj45|dac)\b)",
            re.IGNORECASE,
        ),
    }

    STOP_WORDS = {
        "a", "an", "the", "and", "or", "in", "on", "at", "to", "for", "with",
        "by", "of", "from", "is", "are", "per", "ea", "nos", "qty", "set"
    }

    @classmethod
    def clean_sku(cls, raw_sku: Optional[str]) -> Optional[str]:
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
    def _get_tokens(cls, text: str) -> Set[str]:
        tokens = re.findall(r"[A-Za-z0-9]+", text.lower())
        return {t for t in tokens if len(t) > 1 and t not in cls.STOP_WORDS}

    @classmethod
    def _get_spec_attributes(cls, text: str) -> Dict[str, Set[str]]:
        specs: Dict[str, Set[str]] = {}
        for category, pattern in cls.SPEC_PATTERNS.items():
            matches = pattern.findall(text)
            specs[category] = {re.sub(r"\s+", "", m.lower()) for m in matches}
        return specs

    @classmethod
    def match_exact_sku(
        cls,
        target_sku: str,
        vendor_sku_map: Dict[str, Tuple[int, CanonicalItem]],
        used_indices: Set[int],
    ) -> Optional[Tuple[int, CanonicalItem, float, MatchStage, MatchVerdict, List[str]]]:
        clean = cls.clean_sku(target_sku)
        if not clean:
            return None

        if clean in vendor_sku_map:
            idx, item = vendor_sku_map[clean]
            if idx not in used_indices:
                return idx, item, 1.0, MatchStage.EXACT_SKU, MatchVerdict.IDENTICAL, []
        return None

    @classmethod
    def match_sku_in_text(
        cls,
        target_sku: str,
        vendor_items: List[CanonicalItem],
        used_indices: Set[int],
    ) -> Optional[Tuple[int, CanonicalItem, float, MatchStage, MatchVerdict, List[str]]]:
        clean = cls.clean_sku(target_sku)
        if not clean or len(clean) < 4:
            return None

        pattern = re.compile(rf"\b{re.escape(clean)}\b", re.IGNORECASE)

        for idx, item in enumerate(vendor_items):
            if idx in used_indices:
                continue

            blob = f"{item.raw_text or ''} {item.product_name or ''} {item.description_and_specs or ''}"
            blob_normalized = re.sub(r"[\s\-_=\./\\#:]+", "", blob.upper())

            if pattern.search(blob) or clean in blob_normalized:
                return idx, item, 0.95, MatchStage.TOKEN_REGEX, MatchVerdict.IDENTICAL, []

        return None

    @classmethod
    def match_description(
        cls,
        target_desc: str,
        vendor_items: List[CanonicalItem],
        used_indices: Set[int],
        threshold: float = 0.45,  # Relaxed slightly to handle brand/unit variations
    ) -> Optional[Tuple[int, CanonicalItem, float, MatchStage, MatchVerdict, List[str]]]:
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

            vendor_blob = f"{item.product_id or ''} {item.product_name or ''} {item.description_and_specs or ''} {item.raw_text or ''}"
            vendor_tokens = cls._get_tokens(vendor_blob)
            if not vendor_tokens:
                continue

            intersection = target_tokens.intersection(vendor_tokens)
            union = target_tokens.union(vendor_tokens)
            score = len(intersection) / len(union) if union else 0.0

            # Only apply penalty if both sides explicitly identified conflicting specs in the same category
            vendor_specs = cls._get_spec_attributes(vendor_blob)
            diffs: List[str] = []
            penalty = 0.0

            for cat in ["length", "speed", "form_factor"]:
                t_val = target_specs.get(cat)
                v_val = vendor_specs.get(cat)
                # Only penalize if both explicitly defined specs that conflict (e.g. 10G vs 1000BASE)
                if t_val and v_val and not t_val.intersection(v_val):
                    diffs.append(f"Mismatched {cat}: Requested {t_val} vs Quoted {v_val}")
                    penalty += 0.20

            adjusted_score = max(0.0, score - penalty)

            if adjusted_score > best_score:
                best_score = adjusted_score
                best_item = (idx, item)
                best_diffs = diffs

        if best_item and best_score >= threshold:
            confidence = round(min(0.95, 0.60 + (best_score * 0.35)), 2)
            verdict = (
                MatchVerdict.IDENTICAL
                if confidence >= 0.80 and not best_diffs
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
        candidates = [(idx, item) for idx, item in enumerate(vendor_items) if idx not in used_indices]
        if not candidates:
            return None

        lines = [
            f"[{c_idx}] SKU: {item.product_id or 'N/A'} | Desc: {item.description_and_specs or item.product_name or item.raw_text or 'N/A'}"
            for c_idx, item in candidates
        ]
        user_prompt = (
            f"Customer Requirement:\n\"{target_desc}\"\n\n"
            f"Vendor Line Item Candidates:\n" + "\n".join(lines) + "\n\n"
            "Rules for matching:\n"
            "- Industry standard part numbers (e.g. 'GLC-TE=' for 1000BASE-T or 'SFP-H10GB-CU3M=' for 10GBASE-CU) represent the exact Cisco items requested.\n"
            "- If a candidate matches the technical specs, select its index.\n"
            "Return the single best matching index or -1 if no equivalent item is offered."
        )

        try:
            from pydantic import BaseModel, Field

            class LLMMatchDecision(BaseModel):
                chosen_index: int = Field(default=-1)
                is_exact: bool = Field(default=False)
                confidence: float = Field(default=0.0)
                reason: str = Field(default="")

            decision = llm_client.generate_response(
                system_prompt="You are an expert IT hardware procurement arbitrator. Accurately identify equivalent transceiver and cabling parts even if the vendor description omits the brand prefix.",
                user_content=user_prompt,
                response_schema=LLMMatchDecision,
            )

            if decision and decision.chosen_index in dict(candidates):
                item = next(it for (i, it) in candidates if i == decision.chosen_index)
                verdict = MatchVerdict.IDENTICAL if decision.is_exact else MatchVerdict.COMPATIBLE_SUBSTITUTE
                conf = max(0.70, min(0.95, decision.confidence or 0.85))
                return decision.chosen_index, item, conf, MatchStage.LLM_JUDGE, verdict, [decision.reason]
        except Exception as e:
            logger.warning("Stage 4 (LLM Judge) failed during item evaluation: %s", e)

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
        if target_sku:
            res = cls.match_exact_sku(target_sku, vendor_sku_map, used_indices)
            if res:
                return res

            res = cls.match_sku_in_text(target_sku, vendor_items, used_indices)
            if res:
                return res

        res = cls.match_description(target_desc, vendor_items, used_indices)
        if res:
            return res

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
        client_name: Optional[str] = None,
        llm_client: Optional[BaseLLMClient] = None,
    ) -> MultiVendorComparisonReport:
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

        for row_idx, bom_item in enumerate(client_bom, start=1):
            req_sku = bom_item.get("product_id") or bom_item.get("sku")
            req_desc = bom_item.get("description") or bom_item.get("description_and_specs") or ""
            req_qty = float(bom_item.get("quantity", 1.0))
            req_uom = bom_item.get("unit_of_measure")

            # Diagnostic log
            print(f"\n[DEBUG MATCH] BOM Row {row_idx}: '{req_desc}' (SKU: {req_sku})")


            if req_sku and (" " in req_sku or len(req_sku) > 25):
                if not req_desc:
                    req_desc = req_sku
                req_sku = None

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
                    print(f"[DEBUG ERROR] Exception in match_item for {d_id}: {e}")
                    logger.error("Error matching row %d for doc_id '%s': %s", row_idx, d_id, e)
                    match = None
                    
                print(f"  -> Vendor {vendor_display_name} ({d_id}): Matched = {bool(match)}")

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

            valid_offers = [o for o in vendor_offers.values() if o is not None]
            if valid_offers:
                lowest_unit_price = min(o.unit_price for o in valid_offers)
                highest_unit_price = max(o.unit_price for o in valid_offers)
                recommended_offer = min(valid_offers, key=lambda o: o.total_price)
                rec_doc_id = recommended_offer.doc_id
                rec_vendor_name = recommended_offer.vendor_name
                potential_unit_savings = round(highest_unit_price - lowest_unit_price, 2)
                potential_total_savings = round(potential_unit_savings * req_qty, 2)
            else:
                lowest_unit_price = None
                rec_doc_id = None
                rec_vendor_name = None
                potential_unit_savings = None
                potential_total_savings = None

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
                    recommended_doc_id=rec_doc_id,
                    recommended_vendor_name=rec_vendor_name,
                    potential_unit_savings=potential_unit_savings,
                    potential_total_savings=potential_total_savings,
                )
            )

        # Audit extra items (scope creep) using the UnsolicitedVendorItem schema
        unsolicited_by_doc: Dict[str, List[UnsolicitedVendorItem]] = {}
        unsolicited_spend: Dict[str, float] = {}

        for d_id in all_doc_ids:
            quote = doc_id_to_quote[d_id]
            used = used_items[d_id]
            v_name = doc_metadata[d_id]

            unquoted = [
                UnsolicitedVendorItem(
                    doc_id=d_id,
                    vendor_name=v_name,
                    quote_number=quote.quote_number,
                    product_id=item.product_id,
                    product_name=item.product_name,
                    description_and_specs=item.description_and_specs or item.raw_text,
                    quantity=item.quantity,
                    unit_price=item.unit_price,
                    total_price=item.total_price,
                )
                for idx, item in enumerate(quote.items)
                if idx not in used
            ]
            unsolicited_by_doc[d_id] = unquoted
            unsolicited_spend[d_id] = round(sum(u.total_price for u in unquoted), 2)

        total_req = len(client_bom)
        fully_matched = sum(1 for r in comparison_rows if len(r.missing_from_doc_ids) == 0)
        partially_matched = sum(
            1 for r in comparison_rows if 0 < len(r.missing_from_doc_ids) < len(all_doc_ids)
        )
        unmatched = sum(1 for r in comparison_rows if len(r.missing_from_doc_ids) == len(all_doc_ids))

        compliance_rates = {
            d_id: round((len(used_items[d_id]) / total_req * 100.0), 1) if total_req else 0.0
            for d_id in all_doc_ids
        }
        total_spend = {
            d_id: round(sum(r.vendor_offers[d_id].total_price for r in comparison_rows if r.vendor_offers.get(d_id)), 2)
            for d_id in all_doc_ids
        }
        optimal_spend = round(
            sum(
                min(o.total_price for o in r.vendor_offers.values() if o is not None)
                for r in comparison_rows
                if any(o is not None for o in r.vendor_offers.values())
            ),
            2,
        )
        max_savings = round(sum(r.potential_total_savings or 0.0 for r in comparison_rows), 2)

        best_single_doc = max(compliance_rates.keys(), key=lambda d: (compliance_rates[d], -total_spend[d])) if compliance_rates else None
        best_single_name = doc_metadata.get(best_single_doc, "N/A") if best_single_doc else None

        return MultiVendorComparisonReport(
            client_name=client_name or "Client Requisition",
            doc_metadata=doc_metadata,
            currency=target_currency,
            rows=comparison_rows,
            unsolicited_items_by_doc_id=unsolicited_by_doc,
            total_requested_items=total_req,
            fully_matched_items=fully_matched,
            partially_matched_items=partially_matched,
            unmatched_items=unmatched,
            doc_compliance_rates=compliance_rates,
            total_spend_by_doc_id=total_spend,
            unsolicited_spend_by_doc_id=unsolicited_spend,
            optimal_hybrid_spend=optimal_spend,
            max_potential_savings=max_savings,
            overall_recommended_doc_id=best_single_doc,
            overall_recommended_vendor_name=best_single_name,
        )