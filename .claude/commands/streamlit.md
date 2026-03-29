# Streamlit

Kill any running dashboard instance and relaunch it with the correct API keys.

## Steps

1. Kill any existing `streamlit run dashboard.py` process
2. Wait 1 second
3. Launch `python3 -m streamlit run dashboard.py` from `~/QuantWork/apex_gamma` with env vars `APCA_API_KEY_ID` and `APCA_API_SECRET_KEY` set from the environment or fallback to the known paper keys
4. Wait 5 seconds for startup
5. Confirm it's running and print the local URL
