#!/usr/bin/env bash
#
# Test script for Copier template generation
#
# This script tests the Copier template by:
# 1. Cleaning up any existing test output
# 2. Generating a new project with default answers
# 3. Setting up the environment file
#
# Usage:
#   ./scripts/test_copier_generation.sh
#
# Prerequisites:
#   - copier must be installed (pip install copier or uv add copier)
#   - Must be run from the template repository root
#

set -euo pipefail

# Configuration
TEST_OUTPUT_DIR="/tmp/test_copier_gen"
TEMPLATE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${CYAN}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Step 1: Clean up existing test output
log_info "Step 1: Cleaning up existing test output..."
if [ -d "$TEST_OUTPUT_DIR" ]; then
    rm -rf "$TEST_OUTPUT_DIR"
    log_success "Removed existing directory: $TEST_OUTPUT_DIR"
else
    log_info "No existing directory to remove"
fi

# Step 2: Change to /tmp
log_info "Step 2: Changing to /tmp..."
cd /tmp
log_success "Changed to $(pwd)"

# Step 3: Run copier with default answers
log_info "Step 3: Running copier to generate project..."
log_info "Template source: $TEMPLATE_DIR"
log_info "Output directory: $TEST_OUTPUT_DIR"

# Use --defaults to accept all default values
# Use --vcs-ref HEAD to use the current state (including uncommitted changes)
# Use --data to override specific answers for testing optional features
copier copy --trust --defaults --vcs-ref HEAD \
    --data use_temporal=false --data use_redis=false \
    "$TEMPLATE_DIR" "$TEST_OUTPUT_DIR"

if [ $? -eq 0 ]; then
    log_success "Copier generation completed successfully"
else
    log_error "Copier generation failed"
    exit 1
fi

# Step 4: Change to generated project
log_info "Step 4: Changing to generated project..."
cd "$TEST_OUTPUT_DIR"
log_success "Changed to $(pwd)"

# Step 5: Copy .env.example to .env
log_info "Step 5: Setting up environment file..."
if [ -f ".env.example" ]; then
    cp .env.example .env
    log_success "Copied .env.example to .env"
else
    log_warning ".env.example not found, skipping"
fi

# Summary
echo ""
echo "=========================================="
log_success "Template generation test completed!"
echo "=========================================="
echo ""
echo "Generated project location: $TEST_OUTPUT_DIR"
echo ""
echo "Next steps you can try:"
echo "  cd $TEST_OUTPUT_DIR"
echo "  uv sync --dev"
echo "  uv run pytest tests/ -v"
echo ""
