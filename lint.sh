#!/bin/bash
set -o errexit


# disabling several categories of errors due to false positives in pylint,
# see these issues:
# - https://bitbucket.org/logilab/pylint/issues/701/false-positives-with-not-an-iterable-and
# - https://bitbucket.org/logilab/pylint/issues/58

find varlens/ -name '*.py' \
  | xargs pylint \
  --errors-only \
  --disable=unsubscriptable-object,not-an-iterable,no-member,invalid-unary-operand-type \
&& \
echo 'Passes pylint check' \
&& \
ruff check variform/ \
&& \
echo "Passes ruff check" 
