"""Receipt upload and Gemini-powered structured expense extraction."""

from __future__ import annotations

import base64
import io
import json
from typing import Any, Literal

import httpx2
import pandas as pd
import streamlit as st
from google.genai import errors
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from utils.gemini_client import gemini_configured, run_structured_interaction

ACCEPTED_TYPES = ["jpg", "jpeg", "png", "pdf"]
ExpenseCategory = Literal["Airfare", "Lodging", "Meals", "Ground Transport", "Other"]
CATEGORY_OPTIONS: list[ExpenseCategory] = [
    "Airfare",
    "Lodging",
    "Meals",
    "Ground Transport",
    "Other",
]

_EXTRACTION_INSTRUCTIONS = """Extract the expense details from this receipt.
Return a JSON object matching the supplied schema and containing only these fields:
vendor, date, total_amount, tax, expense_category, project_code.
- date: use YYYY-MM-DD when possible; otherwise preserve the printed date.
- total_amount and tax: numbers in the receipt's currency, without symbols.
- tax: use 0 when no tax is shown.
- expense_category: choose Airfare, Lodging, Meals, Ground Transport, or Other.
- project_code: the project, cost center, or client code printed on the receipt;
  use null when none is present.
Do not infer a project code that is not printed.
"""


class ReceiptExtraction(BaseModel):
    """Validated expense fields extracted from a receipt."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    vendor: str = Field(min_length=1, description="Merchant or airline name")
    date: str = Field(min_length=1, description="Purchase date")
    total_amount: float = Field(description="Grand total in receipt currency")
    tax: float = Field(description="Tax amount; 0 when not shown")
    expense_category: ExpenseCategory
    project_code: str | None


_GEMINI_RECEIPT_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "vendor": {"type": "string"},
        "date": {"type": "string"},
        "total_amount": {"type": "number"},
        "tax": {"type": "number"},
        "expense_category": {
            "type": "string",
            "enum": [str(category) for category in CATEGORY_OPTIONS],
        },
        "project_code": {
            "anyOf": [{"type": "string"}, {"type": "null"}],
        },
    },
    "required": [
        "vendor",
        "date",
        "total_amount",
        "tax",
        "expense_category",
        "project_code",
    ],
}


def extract_receipt(file_name: str, file_bytes: bytes, mime_type: str) -> ReceiptExtraction:
    """Send a receipt to Gemini and validate its structured JSON response."""
    file_type = "document" if mime_type == "application/pdf" else "image"
    output_text = run_structured_interaction(
        contents=[
            {
                "type": "text",
                "text": f"{_EXTRACTION_INSTRUCTIONS}\nUploaded receipt filename: {file_name}",
            },
            {
                "type": file_type,
                "data": base64.b64encode(file_bytes).decode("ascii"),
                "mime_type": mime_type,
            },
        ],
        json_schema=_GEMINI_RECEIPT_JSON_SCHEMA,
    )
    return ReceiptExtraction.model_validate_json(output_text)


def render_expense_collector() -> None:
    """Upload a receipt, extract fields, and offer CSV / JSON downloads."""
    with st.container(border=True):
        st.markdown("##### Upload receipt")
        uploaded = st.file_uploader(
            "Receipt",
            type=ACCEPTED_TYPES,
            accept_multiple_files=False,
            label_visibility="collapsed",
            help="JPG, PNG, or PDF. Phone photos and emailed invoice PDFs both work.",
        )

        mime_type = None
        extract_clicked = False
        if uploaded is not None:
            mime_type = uploaded.type or _guess_mime(uploaded.name)
            st.caption(f"📎 {uploaded.name} · {uploaded.size / 1024:.1f} KB · {mime_type}")
            extract_clicked = st.button("Extract expense", type="primary")

    if uploaded is not None and mime_type is not None and extract_clicked:
        try:
            with st.spinner("Reading the receipt with Gemini…"):
                extraction = extract_receipt(uploaded.name, uploaded.getvalue(), mime_type)
        except httpx2.RequestError as exc:
            st.error(
                "Could not connect to Gemini. Check your internet/DNS connection, then try again."
            )
            st.caption(f"Connection details: {exc}")
        except (RuntimeError, ValueError, ValidationError, errors.APIError) as exc:
            st.error(f"Extraction failed: {exc}")
        else:
            st.session_state.pop("receipt_expense_editor", None)
            st.session_state["receipt_extraction"] = extraction

    extraction = st.session_state.get("receipt_extraction")
    if isinstance(extraction, ReceiptExtraction):
        st.divider()
        _render_extraction(extraction)
        return

    if not gemini_configured():
        _render_manual_fallback(
            enabled_message=(
                "Add GOOGLE_API_KEY or GEMINI_API_KEY to Streamlit secrets to enable "
                "Gemini. You can still enter the fields below to produce CSV or JSON."
            )
        )
    elif uploaded is None:
        st.info("Upload a JPG, PNG, or PDF receipt, then extract the expense.")


def receipts_to_frame(extractions: list[ReceiptExtraction]) -> pd.DataFrame:
    """Tabular view used by the on-screen table and the CSV download."""
    rows = [item.model_dump() for item in extractions]
    for row in rows:
        row["project_code"] = row["project_code"] or ""
    return pd.DataFrame(rows)


def _render_extraction(extraction: ReceiptExtraction) -> None:
    st.subheader("Review extracted expense")

    col_vendor, col_total, col_category = st.columns(3)
    col_vendor.metric("Vendor", extraction.vendor)
    col_total.metric("Total amount", f"{extraction.total_amount:.2f}")
    col_category.metric("Category", extraction.expense_category)

    st.caption("Click a cell to edit. Valid changes are included in both downloads.")
    frame = receipts_to_frame([extraction])
    edited_frame = st.data_editor(
        frame,
        key="receipt_expense_editor",
        width="stretch",
        hide_index=True,
        num_rows="fixed",
        column_config={
            "vendor": st.column_config.TextColumn("Vendor", required=True),
            "date": st.column_config.TextColumn("Date", required=True),
            "total_amount": st.column_config.NumberColumn(
                "Total amount", format="%.2f", step=0.01, required=True
            ),
            "tax": st.column_config.NumberColumn(
                "Tax", format="%.2f", step=0.01, required=True
            ),
            "expense_category": st.column_config.SelectboxColumn(
                "Expense category", options=CATEGORY_OPTIONS, required=True
            ),
            "project_code": st.column_config.TextColumn(
                "Project code", help="Add or correct the project or cost-center code."
            ),
        },
    )
    edited_row = edited_frame.iloc[0].to_dict()
    project_code = edited_row.get("project_code")
    if project_code is None or pd.isna(project_code):
        edited_row["project_code"] = None
    else:
        edited_row["project_code"] = str(project_code).strip() or None

    try:
        updated_extraction = ReceiptExtraction.model_validate(edited_row)
    except ValidationError as exc:
        st.error(f"Please correct the invalid fields before downloading: {exc}")
        return

    if updated_extraction != extraction:
        st.session_state["receipt_extraction"] = updated_extraction
    extraction = updated_extraction
    frame = receipts_to_frame([extraction])

    json_bytes = json.dumps(extraction.model_dump(), indent=2).encode("utf-8")
    csv_buffer = io.StringIO()
    frame.to_csv(csv_buffer, index=False)

    col_csv, col_json = st.columns(2)
    with col_csv:
        st.download_button(
            "Download CSV",
            data=csv_buffer.getvalue(),
            file_name="expense.csv",
            mime="text/csv",
            width="stretch",
        )
    with col_json:
        st.download_button(
            "Download JSON",
            data=json_bytes,
            file_name="expense.json",
            mime="application/json",
            width="stretch",
        )


def _render_manual_fallback(enabled_message: str) -> None:
    """Keep expense export usable before a Gemini key is available."""
    if not gemini_configured():
        st.info(enabled_message)

    with st.container(border=True), st.form("manual_receipt"):
        st.markdown("##### Manual entry")
        col_vendor, col_date = st.columns(2)
        with col_vendor:
            vendor = st.text_input("Vendor")
        with col_date:
            spent_on = st.text_input("Date", placeholder="YYYY-MM-DD")

        col_total, col_tax = st.columns(2)
        with col_total:
            total_amount = st.number_input("Total amount", min_value=0.0, value=0.0, step=0.01)
        with col_tax:
            tax = st.number_input("Tax", min_value=0.0, value=0.0, step=0.01)

        col_category, col_project = st.columns(2)
        with col_category:
            category = st.selectbox("Expense category", CATEGORY_OPTIONS)
        with col_project:
            project_code = st.text_input("Project code")

        submitted = st.form_submit_button("Save manual expense", type="primary")

    if not submitted:
        return
    try:
        extraction = ReceiptExtraction(
            vendor=vendor.strip() or "Unknown vendor",
            date=spent_on.strip() or "unknown",
            total_amount=float(total_amount),
            tax=float(tax),
            expense_category=category,
            project_code=project_code.strip() or None,
        )
    except ValidationError as exc:
        st.error(str(exc))
        return
    st.session_state.pop("receipt_expense_editor", None)
    st.session_state["receipt_extraction"] = extraction
    _render_extraction(extraction)


def _guess_mime(file_name: str) -> str:
    lower = file_name.lower()
    if lower.endswith(".png"):
        return "image/png"
    if lower.endswith(".pdf"):
        return "application/pdf"
    return "image/jpeg"
