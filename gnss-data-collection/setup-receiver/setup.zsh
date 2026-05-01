#!/bin/zsh

# --- COLOR DEFINITIONS ---
BLUE='\033[1;34m'
GREEN='\033[1;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# --- HELPER FUNCTION ---
print_step() {
    echo -e "\n${BLUE}============================================================${NC}"
    echo -e "${GREEN}▶ Running: ${YELLOW}$1${NC}"
    echo -e "${BLUE}============================================================${NC}"
}

echo -e "${GREEN}Starting U-blox Configuration Sequence...${NC}"

# STEP 1: Reset
print_step "uv run 01-reset.py"
uv run 01-reset.py
# 10-second in-place countdown
for i in {10..1}; do
    printf "\r${YELLOW}Waiting %d seconds for receiver to cold boot...${NC}" "$i"
    sleep 1
done
echo "" # Print a newline when done so the next command doesn't overwrite it

# STEP 2: Sample Rate
print_step "uv run 02-sample-rate.py"
uv run 02-sample-rate.py
sleep 1

# STEP 3: Port Config
print_step "uv run 03-port-config.py"
uv run 03-port-config.py
sleep 1

# STEP 4: Messages
print_step "uv run 04-messages.py"
uv run 04-messages.py
sleep 1

# STEP 5: Save Config
print_step "uv run 05-save-config.py"
uv run 05-save-config.py
# 5-second in-place countdown
for i in {5..1}; do
    printf "\r${YELLOW}Waiting %d seconds for flash write to complete...${NC}" "$i"
    sleep 1
done
echo "" # Print a newline when done

# STEP 6: Check Config
print_step "uv run 06-check.py"
uv run 06-check.py
sleep 2
