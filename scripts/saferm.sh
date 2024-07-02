#! /bin/bash

# A safe rm which can prevent unintetionally removing files outside of the designated root

# Turn on exit on failure
set -e

if [ $# -lt 1 ]; then
  echo "Usage: saferm.sh \$ROOT objects"
  exit 1
fi

SELF=$0
ROOT=$1
ROOTPATH=$(realpath $ROOT)
OBJECTS=${@:2}

# Ensure that ROOT is a directory
if [ -f "$ROOT" ]; then
  echo "ROOT ('$ROOT') must be a directory, not a regular file."
  exit 1
fi

# If there are no objects, end
if [ -z "$OBJECTS" ]; then
  exit 0
fi

OBJECTS_FILTERED=""

for obj in "${@:2}"; do
  # Ensure that this script is not in 'objects'
  if [ "$SELF" -ef "$obj" ]; then
    echo "$SELF found in list of objects. Cannot delete self!"
    exit 1
  fi
  # Skip anything starting with dash
  if [[ "$obj" == -* ]]; then
    # Add all flags unaltered
    OBJECTS_FILTERED="$OBJECTS_FILTERED $obj"
  else
    # Ensure no path in 'objects' attempts to reach outside of ROOT
    OBJPATH=$(realpath $obj 2> /dev/null || echo "")
    if [ -n "$OBJPATH" ]; then
      OBJECTS_FILTERED="$OBJECTS_FILTERED $obj"
      if [[ "$OBJPATH" != $ROOTPATH* ]]; then
        echo "Path $OBJPATH reaches above $ROOTPATH. Disallowed"
        exit 1
      fi
    fi
  fi
done

# Finally pass objects to rm
echo "rm $OBJECTS_FILTERED"
rm $OBJECTS_FILTERED
