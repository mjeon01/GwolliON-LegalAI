"""Tests never depend on a locally trained clause model; tests that need one build their own."""
import os

os.environ["GWOLLION_CLAUSE_MODEL"] = "off"
