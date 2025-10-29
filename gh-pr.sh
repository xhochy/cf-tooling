#!/bin/zsh

gh-pr() {
    # Check if a URL was provided
    if [ -z "$1" ]; then
        echo "Error: Please provide a GitHub PR URL"
        echo "Usage: gh-pr https://github.com/owner/repo/pull/123"
        return 1
    fi

    local url="$1"

    # Strip fragment (everything from # onwards)
    url="${url%%#*}"

    # Extract owner, repo, and PR number from URL
    # Expected format: https://github.com/owner/repo/pull/123
    if [[ ! "$url" =~ ^https://github\.com/([^/]+)/([^/]+)/pull/([0-9]+)$ ]]; then
        echo "Error: Invalid GitHub PR URL format"
        echo "Expected: https://github.com/owner/repo/pull/123"
        return 1
    fi

    local owner="${match[1]}"
    local repo="${match[2]}"
    local pr_number="${match[3]}"

    # Check if the repository folder exists
    if [ ! -d "$repo" ]; then
        gh repo fork "$owner/$repo" --clone=true
        if [ $? -ne 0 ]; then
            return 1
        fi
    fi

    # Change into the repository directory
    cd "$repo" || {
        return 1
    }

    # Fetch all updates from upstream
    git fetch -a upstream
    if [ $? -ne 0 ]; then
        :
    fi

    # Checkout the PR
    gh pr checkout "$pr_number"
    if [ $? -ne 0 ]; then
        return 1
    fi

    echo "Successfully checked out PR #$pr_number"
}
