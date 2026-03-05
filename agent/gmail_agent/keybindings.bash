# Source this file in Bash to enable quick aliases + Alt+g keybindings.
# Usage:
#   source /home/ub/code/agent/agent/gmail_agent/keybindings.bash

alias gam='gmail-agent menu'
alias gab='gmail-agent gmail briefing --lookback-days 7'
alias gac='gmail-agent gmail mdt-check --initials UB --week current'
alias gan='gmail-agent gmail mdt-check --initials UB --week next'
alias gas='gmail-agent gmail mdt-snooze'
alias gal='gmail-agent linkedin run-once'

# Readline keybindings: press Alt+g, then key.
bind '"\egm":"gmail-agent menu\C-m"'
bind '"\egb":"gmail-agent gmail briefing --lookback-days 7\C-m"'
bind '"\egc":"gmail-agent gmail mdt-check --initials UB --week current\C-m"'
bind '"\egn":"gmail-agent gmail mdt-check --initials UB --week next\C-m"'
bind '"\egs":"gmail-agent gmail mdt-snooze\C-m"'
bind '"\egl":"gmail-agent linkedin run-once\C-m"'
