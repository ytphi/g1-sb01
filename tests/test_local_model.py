#!/usr/bin/env python3
"""
test_local_model.py  -  offline check of SB01_LLM=local (replies from a model on this computer, through Ollama)

Ollama is a stand-in here: what is checked is what Yotie sends it and what Yotie
does with the answer, not how good the model's answers are.

  python3 -m unittest tests.test_local_model -v      (from the project root)
"""

import contextlib
import io
import json
import os
import sys
import unittest
import urllib.error
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from tests import test_language as base

script = base.script


class _Ollama:
    """Answers every request with `reply`, or fails with `error`; keeps what was sent."""

    def __init__(self, reply="Hello there.", error=None):
        self.reply, self.error, self.sent = reply, error, []

    def __call__(self, request, timeout=None):
        self.sent.append((request.full_url, json.loads(request.data), timeout))
        if self.error:
            raise self.error
        answer = io.BytesIO(json.dumps({"message": {"role": "assistant", "content": self.reply}}).encode())
        return contextlib.closing(answer)


def _ask_locally(text, reply="Hello there.", whisper=None):
    ollama = _Ollama(reply)
    with mock.patch.object(script, "LLM", "local"), mock.patch.object(script.urllib.request, "urlopen", ollama):
        loop = base._new_loop()
        loop.web_context = "--- course material: 00_syllabus.md ---\nLectures: Monday and Wednesday."
        with contextlib.redirect_stdout(io.StringIO()):
            spoken, _ = loop._ask_claude(text, "", whisper)
    return loop, ollama, spoken


class AskingTheLocalModel(unittest.TestCase):
    def test_claude_is_still_the_default(self):
        self.assertEqual(script.LLM, "claude")
        loop = base._new_loop()
        base.reply_text["value"] = "Hi from Claude."
        self.assertEqual(loop._ask_claude("Hello there friend", "")[0], "Hi from Claude.")
        self.assertEqual(len(base.claude_calls), 1)

    def test_the_question_goes_to_ollama_and_not_to_claude(self):
        loop, ollama, spoken = _ask_locally("When does our class meet?", "On Monday and Wednesday.")
        self.assertEqual(spoken, "On Monday and Wednesday.")
        self.assertEqual(base.claude_calls, [])
        self.assertIsNone(loop.claude)
        url, body, timeout = ollama.sent[-1]
        self.assertEqual(url, script.LOCAL_URL + "/api/chat")
        self.assertEqual(body["model"], script.LOCAL_MODEL)
        self.assertEqual(timeout, script.LOCAL_SECONDS)

    def test_the_model_gets_the_instructions_course_notes_and_language_note(self):
        _, ollama, _ = _ask_locally("When does our class meet?")
        body = ollama.sent[-1][1]
        system, *messages = body["messages"]
        self.assertEqual(system["role"], "system")
        self.assertIn("You are Yotie,", system["content"])
        self.assertIn("Lectures: Monday and Wednesday.", system["content"])
        self.assertTrue(system["content"].endswith(script.LOCAL_PROMPT))
        self.assertTrue(messages[-1]["content"].startswith("[Reply in English.]"))

    def test_the_notes_fit_and_the_model_stays_loaded(self):
        _, ollama, _ = _ask_locally("When does our class meet?")
        body = ollama.sent[-1][1]
        self.assertEqual(body["options"]["num_ctx"], script.LOCAL_CONTEXT_TOKENS)
        self.assertEqual(body["keep_alive"], -1)
        self.assertIs(body["stream"], False)
        self.assertIs(body["think"], False)

    def test_the_reply_is_remembered_for_the_next_question(self):
        loop, _, spoken = _ask_locally("What camera does the G1 use?", "The Intel RealSense D435i.")
        self.assertEqual(loop.history[-1], {"role": "assistant", "content": spoken})

    def test_the_name_is_corrected_as_with_claude(self):
        _, _, spoken = _ask_locally("Who are you?", "I am Yodee, your assistant.")
        self.assertEqual(spoken, "I am Yotie, your assistant.")

    def test_no_api_key_is_needed(self):
        with mock.patch.object(script, "LLM", "local"), mock.patch.dict(os.environ):
            os.environ.pop("ANTHROPIC_API_KEY", None)
            self.assertIsNone(base._new_loop().claude)

    def test_an_unknown_setting_stops_at_startup(self):
        with mock.patch.object(script, "LLM", "gemini"), self.assertRaises(SystemExit) as stop:
            base._new_loop()
        self.assertIn("use claude or local", str(stop.exception))


class WhatIsSpoken(unittest.TestCase):
    """Small models wrap a reply in things that would be read aloud."""

    def spoken(self, reply):
        with mock.patch.object(script.urllib.request, "urlopen", _Ollama(reply)):
            return script.ask_local("system", [{"role": "user", "content": "hi"}], 50)

    def test_a_language_label_in_front_is_removed(self):
        self.assertEqual(self.spoken("[Spanish] Nuestra clase es el lunes."), "Nuestra clase es el lunes.")
        self.assertEqual(self.spoken("(In Italian) Il corso è il lunedì."), "Il corso è il lunedì.")

    def test_a_translation_or_note_at_the_end_is_removed(self):
        self.assertEqual(self.spoken("수업은 월요일입니다. (Our class meets on Mondays in CGI-112.)"), "수업은 월요일입니다.")
        self.assertEqual(self.spoken("Kelas kita pada hari Isnin. [course material: 00_syllabus.md]"), "Kelas kita pada hari Isnin.")

    def test_teaching_gesture_marks_are_kept(self):
        self.assertEqual(self.spoken("[yes] Yes, exactly right."), "[yes] Yes, exactly right.")
        self.assertEqual(self.spoken("Look at the [point] diagram. Any [ask] questions?"),
                         "Look at the [point] diagram. Any [ask] questions?")

    def test_brackets_inside_a_sentence_are_kept(self):
        self.assertEqual(self.spoken("Class starts at 17h30 (5:30 PM) on Mondays."), "Class starts at 17h30 (5:30 PM) on Mondays.")

    def test_markdown_and_reasoning_are_removed(self):
        self.assertEqual(self.spoken("<think>hmm</think>It is a **stereo** camera."), "It is a stereo camera.")

    def test_a_reply_that_is_only_a_note_is_still_said(self):
        self.assertEqual(self.spoken("(A reply entirely in brackets, nothing more.)"), "(A reply entirely in brackets, nothing more.)")

    def test_an_empty_reply_is_an_error_so_the_robot_apologises(self):
        with self.assertRaises(RuntimeError):
            self.spoken("   ")


class AtTheEnd(unittest.TestCase):
    def test_the_model_is_unloaded(self):
        ollama = _Ollama()
        with mock.patch.object(script.urllib.request, "urlopen", ollama):
            script.release_local()
        url, body, _ = ollama.sent[-1]
        self.assertEqual(url, script.LOCAL_URL + "/api/generate")
        self.assertEqual(body, {"model": script.LOCAL_MODEL, "keep_alive": 0})

    def test_ollama_being_gone_is_not_an_error(self):
        down = urllib.error.URLError(ConnectionRefusedError("refused"))
        with mock.patch.object(script.urllib.request, "urlopen", _Ollama(error=down)):
            script.release_local()


class WhenOllamaIsNotThere(unittest.TestCase):
    def test_a_missing_model_is_reported(self):
        missing = urllib.error.HTTPError(script.LOCAL_URL, 404, "Not Found", {}, io.BytesIO(b'{"error":"model not found"}'))
        with mock.patch.object(script.urllib.request, "urlopen", _Ollama(error=missing)), \
                self.assertRaisesRegex(RuntimeError, "404.*model not found"):
            script.ask_local("system", [], 10)

    def test_startup_stops_with_what_to_do(self):
        down = urllib.error.URLError(ConnectionRefusedError("refused"))
        with mock.patch.object(script, "LLM", "local"), \
                mock.patch.object(script.urllib.request, "urlopen", _Ollama(error=down)):
            loop = base._new_loop()
            with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as stop:
                loop._warm_local_model()
        self.assertIn("NOT available", str(stop.exception))
        self.assertIn("ollama pull", str(stop.exception))

    def test_a_slow_load_says_memory_not_missing(self):
        slow = urllib.error.URLError(TimeoutError("timed out"))
        with mock.patch.object(script, "LLM", "local"), \
                mock.patch.object(script.urllib.request, "urlopen", _Ollama(error=slow)):
            loop = base._new_loop()
            with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as stop:
                loop._warm_local_model()
        self.assertIn("short of memory", str(stop.exception))
        self.assertNotIn("ollama pull", str(stop.exception))

    def test_startup_reads_the_notes_once_with_a_longer_wait(self):
        ollama = _Ollama("Hi")
        with mock.patch.object(script, "LLM", "local"), mock.patch.object(script.urllib.request, "urlopen", ollama):
            loop = base._new_loop()
            with contextlib.redirect_stdout(io.StringIO()):
                loop._warm_local_model()
            instructions = loop._build_system_prompt()
        _, body, timeout = ollama.sent[-1]
        self.assertEqual(timeout, script.LOCAL_FIRST_SECONDS)
        self.assertEqual(body["messages"][0]["content"], instructions)   # the same text the questions start with


if __name__ == "__main__":
    unittest.main()
