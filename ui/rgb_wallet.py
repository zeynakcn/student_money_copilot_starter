"""RGB wallet tab: STUSD balance and the rent payment flow.

Place this file at ui/rgb_wallet.py. It uses rgb_client.py (project root).
A payment is only sent after: Prepare -> tick the confirmation box -> Confirm & Send.
"""
import streamlit as st

from rgb_client import get_stusd_balance, send_stusd_payment

PREPARED_KEY = "rgb_payment_prepared"


def _balance():
    """Return (balance_dict, error_text)."""
    try:
        data = get_stusd_balance()
        return {
            "settled": int(data.get("settled", 0)),
            "future": int(data.get("future", 0)),
            "spendable": int(data.get("spendable", 0)),
        }, None
    except Exception as error:
        return None, str(error)


def render_rgb_wallet(expenses: list[dict]):
    st.subheader("₿ RGB Wallet")

    balance, error = _balance()
    if balance is None:
        st.error(
            "Could not read the RGB wallet. Make sure Docker, studentcopilot, "
            "and landlord2 are running and unlocked."
        )
        st.code(error)
    else:
        col1, col2, col3 = st.columns(3)
        col1.metric("Settled", f"{balance['settled']} STUSD")
        col2.metric("Future", f"{balance['future']} STUSD")
        col3.metric("Spendable", f"{balance['spendable']} STUSD")
        if balance["settled"] != balance["future"]:
            st.info(
                "An RGB transfer is pending. "
                f"The wallet currently projects {balance['future']} STUSD after pending transfers."
            )
        else:
            st.success("RGB wallet is synced.")
    if st.button("Refresh balance", key="rgb_refresh"):
        st.rerun()

    st.divider()
    st.subheader("🏠 Send rent with RGB")

    rent = next(
        (e for e in expenses if str(e.get("name", "")).lower() == "rent"),
        None,
    )
    default_rent = int(float(rent["amount"])) if rent else 250

    rent_amount = st.number_input(
        "Rent payment (STUSD)", min_value=1, value=default_rent, step=1, key="rgb_rent_amount",
    )
    st.caption(
        "This sends a real test-network RGB transaction from studentcopilot to landlord2. "
        "The STUSD amount is separate from the EUR demo budget; no exchange rate is assumed."
    )

    if PREPARED_KEY not in st.session_state:
        st.session_state[PREPARED_KEY] = False

    if st.button("Prepare RGB payment", key="prepare_rgb_payment"):
        st.session_state[PREPARED_KEY] = True

    if st.session_state[PREPARED_KEY]:
        st.warning(f"You are about to send {int(rent_amount)} STUSD on the RGB test network.")
        confirm = st.checkbox(
            "I understand this creates a real test-network RGB transaction.",
            key="rgb_confirm_checkbox",
        )
        col_cancel, col_send = st.columns(2)

        with col_cancel:
            if st.button("Cancel", key="cancel_rgb_payment"):
                st.session_state[PREPARED_KEY] = False
                st.rerun()

        with col_send:
            if st.button("Confirm & Send", key="confirm_rgb_payment", disabled=not confirm):
                # Close the confirmation first so a double click cannot send twice.
                st.session_state[PREPARED_KEY] = False

                fresh, fresh_error = _balance()
                if fresh is None:
                    st.error("Could not verify the wallet balance, so nothing was sent.")
                    st.code(fresh_error)
                elif int(rent_amount) > fresh["spendable"]:
                    st.error(
                        f"Not enough spendable STUSD: {fresh['spendable']} available, "
                        f"{int(rent_amount)} requested. Nothing was sent."
                    )
                else:
                    with st.spinner("Creating landlord invoice and sending STUSD..."):
                        try:
                            result = send_stusd_payment(int(rent_amount))
                            txid = result.get("txid", "Transaction created")
                            st.session_state["last_rgb_txid"] = txid
                            st.success(
                                "✅ RGB payment created. It may stay pending until it confirms; "
                                "do not send it again."
                            )
                        except Exception as send_error:
                            st.error("RGB payment failed.")
                            st.code(str(send_error))

    if st.session_state.get("last_rgb_txid"):
        st.caption("Most recent RGB transaction")
        st.code(st.session_state["last_rgb_txid"])