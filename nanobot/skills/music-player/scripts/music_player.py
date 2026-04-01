#!/usr/bin/env python3
"""
Music Player Skill - Search and serve MP3 files
"""

import os
import sys
import argparse
from pathlib import Path
from typing import List, Tuple

MP3_DIR = Path(__file__).parent.parent / "mp3"

def find_mp3_files() -> List[Path]:
    """Find all MP3 files in the mp3 directory"""
    if not MP3_DIR.exists():
        return []
    return list(MP3_DIR.glob("**/*.mp3")) + list(MP3_DIR.glob("**/*.MP3"))

def search_songs(query: str) -> List[Tuple[Path, float]]:
    """Search for songs matching the query, returns sorted by relevance"""
    query_lower = query.lower()
    results = []

    for mp3_path in find_mp3_files():
        name_lower = mp3_path.stem.lower()
        # Calculate relevance score
        score = 0.0
        if query_lower in name_lower:
            # Exact substring match
            score = 1.0
            if name_lower == query_lower:
                # Exact name match
                score = 2.0
        elif any(query_lower in word for word in name_lower.split()):
            # Word match
            score = 0.8
        else:
            # Fuzzy match - check characters
            common = set(query_lower) & set(name_lower)
            score = len(common) / max(len(query_lower), len(name_lower)) * 0.5

        if score > 0:
            results.append((mp3_path, score))

    # Sort by score descending
    results.sort(key=lambda x: x[1], reverse=True)
    return results

def list_songs() -> None:
    """List all available songs"""
    mp3_files = find_mp3_files()
    if not mp3_files:
        print("No MP3 files found in mp3/ directory")
        return

    print(f"Available songs ({len(mp3_files)}):")
    for path in sorted(mp3_files):
        size_mb = path.stat().st_size / (1024 * 1024)
        print(f"  - {path.stem} ({size_mb:.1f} MB)")
        print(f"    Path: {path.absolute()}")

def main():
    parser = argparse.ArgumentParser(description='Music Player Skill')
    subparsers = parser.add_subparsers(dest='command', required=True)

    # List command
    subparsers.add_parser('list', help='List all available songs')

    # Search command
    search_parser = subparsers.add_parser('search', help='Search for songs')
    search_parser.add_argument('query', help='Search query')

    # Play command
    play_parser = subparsers.add_parser('play', help='Get path to song for playing')
    play_parser.add_argument('song_name', help='Song name to play')

    args = parser.parse_args()

    if args.command == 'list':
        list_songs()

    elif args.command == 'search':
        results = search_songs(args.query)
        if not results:
            print(f"No songs found matching '{args.query}'")
            sys.exit(1)

        print(f"Found {len(results)} matching song(s):")
        for i, (path, score) in enumerate(results, 1):
            size_mb = path.stat().st_size / (1024 * 1024)
            print(f"  {i}. {path.stem} ({size_mb:.1f} MB) - match: {score:.2f}")
            print(f"     Path: {path.absolute()}")

    elif args.command == 'play':
        results = search_songs(args.song_name)
        if not results:
            print(f"No songs found matching '{args.song_name}'")
            sys.exit(1)

        best_match = results[0][0]
        # Print just the absolute path for easy consumption
        print(best_match.absolute())

if __name__ == '__main__':
    main()
