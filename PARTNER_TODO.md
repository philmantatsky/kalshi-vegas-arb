# Partner Handoff Checklist

## Your job: get the bot running on Oracle Cloud before 5 PM CT Sunday

- [ ] Create Oracle Cloud VM — Ubuntu 22.04 ARM (Ampere A1.Flex), 1 OCPU / 6 GB RAM is fine
- [ ] SSH into the VM
- [ ] Follow every step in **RUNBOOK.md** (it's in the repo)
- [ ] When you get to Step 3 (.env), ask Phil for the API keys and fill them in
- [ ] Run the bot manually (Step 5) and confirm you see ticks firing
- [ ] Set up the systemd service (Step 6) and confirm `Active: active (running)`
- [ ] Tell Phil it's running — he'll do the slug switch at 5 PM CT

That's it. Everything else is automated.
