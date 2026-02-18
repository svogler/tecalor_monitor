# How it works

First run: saves the current 36 entries as baseline → no email sent<br /> 
Subsequent runs: compares against the saved state; any new (error_code, heatpump, date, time) triggers an email<br /> 
State is only updated after a successful email send — so if the email fails, the next run will retry<br /> 

# Cron setup

`crontab -e`<br /> 
Add (adjust paths and interval as needed):<br /> 

`*/15 * * * * /usr/bin/python3 monitor.py >> monitor.log 2>&1`

# Test without waiting for a real new error
After the first run creates `state.json`, delete one entry from it and run again — the script will treat it as a new error and send an email.
