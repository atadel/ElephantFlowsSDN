while true; do sudo mnexec -a $(pgrep -f "mininet:h[1-6]" | shuf -n 1) python3 random_sender.py; done
