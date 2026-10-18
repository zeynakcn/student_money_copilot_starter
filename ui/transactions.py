"""Transaction history (EUR sample data).

Place this file at ui/transactions.py. The live RGB wallet and payment flow
are rendered above it by ui/rgb_wallet.py on the same page.
"""
import streamlit as st


def render_transactions(expenses: list[dict], transactions: list[dict]):
    st.subheader("Transaction history · EUR demo")
    st.caption(
        "These entries come from the sample transactions file, not from the RGB blockchain. "
        "RGB payments appear in the wallet section above."
    )
    if not transactions:
        st.info("No recorded spending yet.")
        return

    rows = []
    for tx in sorted(transactions, key=lambda t: str(t.get("date", "")), reverse=True):
        rows.append({
            "Date": str(tx.get("date", "")),
            "Merchant": str(tx.get("merchant", tx.get("name", "—"))),
            "Category": str(tx.get("category", "Other")),
            "Amount (EUR)": f"€{float(tx.get('amount', 0)):,.2f}",
        })
    st.dataframe(rows, hide_index=True, width="stretch")