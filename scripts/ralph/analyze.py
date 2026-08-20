#!/usr/bin/env python3
"""
Complexity Analyzer for PRD/Architecture Documents

Analyzes requirements documents and generates appropriately-sized user stories
based on document complexity.

Usage:
    python analyze.py <prd_file> [architecture_file] [--output prd.json]
"""

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional


@dataclass
class ComplexityFactors:
    """Factors that contribute to overall complexity."""
    functional_requirements: int = 0
    integration_points: int = 0
    ui_components: int = 0
    database_changes: int = 0
    external_apis: int = 0
    authentication_features: int = 0
    file_operations: int = 0
    real_time_features: int = 0

    def calculate_score(self) -> float:
        """Calculate weighted complexity score."""
        return (
            self.functional_requirements * 2 +
            self.integration_points * 3 +
            self.ui_components * 1.5 +
            self.database_changes * 2 +
            self.external_apis * 3 +
            self.authentication_features * 4 +
            self.file_operations * 1.5 +
            self.real_time_features * 3
        ) / 5

    def get_category(self) -> str:
        """Get complexity category based on score."""
        score = self.calculate_score()
        if score <= 5:
            return "simple"
        elif score <= 15:
            return "medium"
        elif score <= 30:
            return "complex"
        else:
            return "enterprise"

    def get_story_count_range(self) -> tuple[int, int]:
        """Get recommended story count range."""
        category = self.get_category()
        ranges = {
            "simple": (5, 10),
            "medium": (10, 25),
            "complex": (25, 50),
            "enterprise": (50, 100),
        }
        return ranges.get(category, (6, 12))

    def get_iteration_estimate(self) -> tuple[int, int]:
        """Get estimated iteration count range."""
        min_stories, max_stories = self.get_story_count_range()
        # Account for potential handoffs and retries
        return (min_stories, int(max_stories * 1.5))


@dataclass
class UserStory:
    """Represents a user story for the PRD."""
    id: str
    title: str
    description: str
    acceptance_criteria: list[str] = field(default_factory=list)
    priority: int = 1
    passes: bool = False
    notes: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "acceptanceCriteria": self.acceptance_criteria,
            "priority": self.priority,
            "passes": self.passes,
            "notes": self.notes,
        }


class ComplexityAnalyzer:
    """Analyzes document complexity and generates sized stories."""

    # Patterns to detect various complexity factors
    PATTERNS = {
        "functional_requirements": [
            r"(?:must|shall|should|will)\s+(?:be able to|allow|enable|support)",
            r"FR-\d+",
            r"requirement[s]?\s*:",
            r"(?:user|system)\s+(?:can|will|should)",
        ],
        "integration_points": [
            r"integrat(?:e|ion|ing)\s+with",
            r"connect(?:s|ing)?\s+to",
            r"(?:third[- ]party|external)\s+(?:service|system|api)",
            r"webhook[s]?",
            r"(?:import|export)\s+(?:from|to)",
        ],
        "ui_components": [
            r"(?:button|form|modal|dialog|dropdown|menu|table|list|card|panel)",
            r"(?:page|screen|view|component|widget)",
            r"(?:display|show|render|present)",
            r"UI/UX",
            r"(?:click|tap|hover|drag|drop)",
        ],
        "database_changes": [
            r"(?:database|db|schema|table|column|field|migration)",
            r"(?:create|update|delete|insert)\s+(?:table|record|row)",
            r"(?:sql|query|index)",
            r"(?:foreign key|primary key|constraint)",
        ],
        "external_apis": [
            r"(?:api|endpoint|rest|graphql|grpc)",
            r"(?:http|https)\s*://",
            r"(?:get|post|put|patch|delete)\s+(?:request|endpoint)",
            r"(?:oauth|api[- ]key|token)",
        ],
        "authentication_features": [
            r"(?:auth|login|logout|signin|signout|signup)",
            r"(?:password|credential|session|jwt|token)",
            r"(?:permission|role|access control|rbac)",
            r"(?:mfa|2fa|two[- ]factor)",
        ],
        "file_operations": [
            r"(?:upload|download|file|attachment|document)",
            r"(?:storage|s3|blob|bucket)",
            r"(?:image|video|audio|media)",
        ],
        "real_time_features": [
            r"(?:real[- ]time|live|streaming|websocket)",
            r"(?:notification|push|alert)",
            r"(?:sync|synchroniz)",
        ],
    }

    def __init__(self, content: str, arch_content: Optional[str] = None):
        self.content = content.lower()
        self.arch_content = (arch_content or "").lower()
        self.combined_content = f"{self.content}\n{self.arch_content}"

    def analyze(self) -> ComplexityFactors:
        """Analyze document and return complexity factors."""
        factors = ComplexityFactors()

        for factor_name, patterns in self.PATTERNS.items():
            count = 0
            for pattern in patterns:
                matches = re.findall(pattern, self.combined_content, re.IGNORECASE)
                count += len(matches)
            setattr(factors, factor_name, min(count, 20))  # Cap at 20 per factor

        return factors

    def extract_feature_name(self) -> str:
        """Extract feature name from document."""
        # Look for title patterns
        title_patterns = [
            r"#\s*(?:PRD|Feature|Product Requirements):\s*(.+)",
            r"#\s*(.+?)(?:\n|$)",
            r"(?:feature|project):\s*(.+?)(?:\n|$)",
        ]

        for pattern in title_patterns:
            match = re.search(pattern, self.content, re.IGNORECASE)
            if match:
                title = match.group(1).strip()
                # Convert to kebab-case
                return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")

        return "feature"

    def extract_project_name(self) -> str:
        """Extract project name from document."""
        patterns = [
            r"project:\s*(.+?)(?:\n|$)",
            r"(?:for|in)\s+(?:the\s+)?([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)*)\s+(?:project|app|application)",
        ]

        for pattern in patterns:
            match = re.search(pattern, self.content, re.IGNORECASE)
            if match:
                return match.group(1).strip()

        return "Project"


def generate_prd_json(
    content: str,
    arch_content: Optional[str],
    output_path: Path,
) -> dict:
    """Generate prd.json from analyzed content."""
    analyzer = ComplexityAnalyzer(content, arch_content)
    factors = analyzer.analyze()

    score = factors.calculate_score()
    category = factors.get_category()
    min_stories, max_stories = factors.get_story_count_range()
    min_iter, max_iter = factors.get_iteration_estimate()

    feature_name = analyzer.extract_feature_name()
    project_name = analyzer.extract_project_name()

    prd = {
        "project": project_name,
        "branchName": f"ralph/{feature_name}",
        "description": f"{feature_name.replace('-', ' ').title()} Feature",
        "complexity": {
            "score": round(score, 1),
            "category": category,
            "estimated_stories": f"{min_stories}-{max_stories}",
            "estimated_iterations": f"{min_iter}-{max_iter}",
            "factors": {
                "functional_requirements": factors.functional_requirements,
                "integration_points": factors.integration_points,
                "ui_components": factors.ui_components,
                "database_changes": factors.database_changes,
                "external_apis": factors.external_apis,
                "authentication_features": factors.authentication_features,
                "file_operations": factors.file_operations,
                "real_time_features": factors.real_time_features,
            },
        },
        "userStories": [],
        "_generated": {
            "timestamp": datetime.now().isoformat(),
            "note": "Stories need to be populated based on PRD analysis",
        },
    }

    return prd


def print_analysis(factors: ComplexityFactors) -> None:
    """Print analysis results."""
    score = factors.calculate_score()
    category = factors.get_category()
    min_stories, max_stories = factors.get_story_count_range()
    min_iter, max_iter = factors.get_iteration_estimate()

    print("\n" + "=" * 50)
    print("  Complexity Analysis Results")
    print("=" * 50)

    print(f"\n  Complexity Score: {score:.1f}")
    print(f"  Category: {category.upper()}")
    print(f"  Recommended Stories: {min_stories}-{max_stories}")
    print(f"  Estimated Iterations: {min_iter}-{max_iter}")

    print("\n  Factor Breakdown:")
    print(f"    Functional Requirements: {factors.functional_requirements}")
    print(f"    Integration Points: {factors.integration_points}")
    print(f"    UI Components: {factors.ui_components}")
    print(f"    Database Changes: {factors.database_changes}")
    print(f"    External APIs: {factors.external_apis}")
    print(f"    Authentication: {factors.authentication_features}")
    print(f"    File Operations: {factors.file_operations}")
    print(f"    Real-time Features: {factors.real_time_features}")

    print("\n" + "=" * 50)


def main():
    parser = argparse.ArgumentParser(
        description="Analyze PRD/Architecture complexity and generate prd.json"
    )
    parser.add_argument("prd_file", help="Path to PRD markdown file")
    parser.add_argument(
        "arch_file",
        nargs="?",
        help="Optional path to architecture document",
    )
    parser.add_argument(
        "--output", "-o",
        default="prd.json",
        help="Output path for prd.json (default: prd.json)",
    )
    parser.add_argument(
        "--analyze-only",
        action="store_true",
        help="Only print analysis, don't generate prd.json",
    )

    args = parser.parse_args()

    # Read PRD file
    prd_path = Path(args.prd_file)
    if not prd_path.exists():
        print(f"Error: PRD file not found: {prd_path}")
        sys.exit(1)

    content = prd_path.read_text()

    # Read architecture file if provided
    arch_content = None
    if args.arch_file:
        arch_path = Path(args.arch_file)
        if arch_path.exists():
            arch_content = arch_path.read_text()
        else:
            print(f"Warning: Architecture file not found: {arch_path}")

    # Analyze
    analyzer = ComplexityAnalyzer(content, arch_content)
    factors = analyzer.analyze()
    print_analysis(factors)

    if args.analyze_only:
        return

    # Generate prd.json
    output_path = Path(args.output)
    prd = generate_prd_json(content, arch_content, output_path)

    output_path.write_text(json.dumps(prd, indent=2))
    print(f"\n  Generated: {output_path}")
    print("  Note: User stories need to be populated manually or via /autonomous-agent-loop convert")


if __name__ == "__main__":
    main()
