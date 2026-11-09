#!/usr/bin/env python3
"""
test_gesture_cues.py  -  offline check of teaching-gesture marks in replies

The marks ("look at the [point] diagram") are taken out of what is spoken and
turned into (gesture, time) pairs for the sidecar. No robot, no Claude, no
network: same stand-ins as tests/test_language.py.

  python3 -m unittest tests.test_gesture_cues -v      (from the project root)
"""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from tests import test_language as base     # loads the real script once, with stand-ins
from teleop import gesture_cues

script = base.script
REPLY = "Great answer. [yes] Yes, that is right. Look at the [point] diagram on the board."
SPOKEN = "Great answer. Yes, that is right. Look at the diagram on the board."
WORDS = [(0.10, "Great"), (0.50, "answer"), (1.20, "Yes"), (1.60, "that"), (1.80, "is"), (2.00, "right"),
         (2.60, "Look"), (2.80, "at"), (2.90, "the"), (3.10, "diagram"), (3.60, "on"), (3.70, "the"), (3.80, "board")]


class Marks(unittest.TestCase):
    def test_marks_are_taken_out_of_the_spoken_text(self):
        spoken, marks = gesture_cues.split(REPLY)
        self.assertEqual(spoken, SPOKEN)
        self.assertEqual([name for name, _ in marks], ["yes", "point"])
        self.assertEqual(spoken[marks[0][1]:].split()[0], "Yes,")           # each mark sits at its word
        self.assertEqual(spoken[marks[1][1]:].split()[0], "diagram")

    def test_text_without_marks_is_untouched(self):
        for text in ("Hello there!", "Use list[0] in Python.", "¿Cómo estás?", "你好"):
            self.assertEqual(gesture_cues.split(text), (text, []))

    def test_an_unknown_mark_is_removed_and_makes_no_gesture(self):
        spoken, marks = gesture_cues.split("That is [dance] wonderful and [YES] correct.")
        self.assertEqual(spoken, "That is wonderful and correct.")
        self.assertEqual([name for name, _ in marks], ["yes"])

    def test_a_translated_mark_is_removed_too(self):
        spoken, marks = gesture_cues.split("Esto es [grande] grande y esto [pequeño] pequeño.")
        self.assertEqual(spoken, "Esto es grande y esto pequeño.")
        self.assertEqual(marks, [])

    def test_every_cue_name_is_recognized(self):
        text = " ".join(f"[{name}] word" for name in gesture_cues.CUE_NAMES)
        self.assertEqual([name for name, _ in gesture_cues.split(text)[1]], list(gesture_cues.CUE_NAMES))

    def test_no_more_than_the_limit(self):
        spoken, marks = gesture_cues.split("[yes] ok " * 30)
        self.assertEqual(len(marks), gesture_cues.MAX_CUES)
        self.assertNotIn("[", spoken)

    def test_marks_work_in_spanish_and_chinese(self):
        spoken, marks = gesture_cues.split("¡[yes] Sí, correcto! 请看[point]黑板。")
        self.assertEqual(spoken, "¡Sí, correcto! 请看黑板。")
        self.assertEqual([name for name, _ in marks], ["yes", "point"])


class Timing(unittest.TestCase):
    def test_a_cue_gets_the_time_of_its_word(self):
        spoken, marks = gesture_cues.split(REPLY)
        self.assertEqual(gesture_cues.timed(marks, WORDS, spoken),
                         [{"name": "yes", "time": 1.2}, {"name": "point", "time": 3.1}])

    def test_a_repeated_word_is_matched_in_order(self):
        spoken, marks = gesture_cues.split("the cat and [point] the dog")
        words = [(0.0, "the"), (0.3, "cat"), (0.6, "and"), (0.9, "the"), (1.2, "dog")]
        self.assertEqual(gesture_cues.timed(marks, words, spoken), [{"name": "point", "time": 0.9}])

    def test_a_mark_at_the_very_end_uses_the_last_word(self):
        spoken, marks = gesture_cues.split("Any questions [ask]")
        self.assertEqual(gesture_cues.timed(marks, [(0.0, "Any"), (0.4, "questions")], spoken),
                         [{"name": "ask", "time": 0.4}])

    def test_without_word_times_there_are_no_cues(self):
        spoken, marks = gesture_cues.split(REPLY)
        self.assertEqual(gesture_cues.timed(marks, [], spoken), [])


class _Gestures:
    """Stands in for the gesture client: records what it is asked, moves nothing."""

    def __init__(self):
        self.starts = []

    def start(self, pcm, **kwargs):
        self.starts.append(kwargs)
        return False

    def __getattr__(self, name):
        return lambda *args, **kwargs: None


class _SpeakingWords:
    """Edge TTS stand-in that also reports when each word starts."""
    asked = []

    def __init__(self, text, voice, **kwargs):
        _SpeakingWords.asked.append((text, kwargs))

    async def stream(self):
        for start, word in WORDS:
            yield {"type": "WordBoundary", "offset": int(start * 1e7), "duration": 1, "text": word}
        yield {"type": "audio", "data": b"mp3"}


class InTheConversation(unittest.TestCase):
    def setUp(self):
        _SpeakingWords.asked = []
        self.loop = base._new_loop()
        self.loop.tts_done.wait = lambda timeout=None: True
        self.loop.gestures = _Gestures()
        self._sleep = mock.patch.object(script.time, "sleep", lambda seconds: None)
        self._sleep.start()

    def tearDown(self):
        self._sleep.stop()

    def test_off_by_default(self):
        self.assertFalse(script.GESTURE_CUES)
        self.assertNotIn("[yes]", self.loop._build_system_prompt())
        self.loop._speak("Plain reply.")
        self.assertEqual(self.loop.gestures.starts, [{}])               # asked exactly as before
        self.assertEqual(base.tts_calls[-1][1], "Plain reply.")

    def test_when_on_claude_is_told_about_the_marks(self):
        with mock.patch.object(script, "GESTURE_CUES", True):
            prompt = self.loop._build_system_prompt()
        for name in ("yes", "point", "one_hand", "other_hand", "small", "big", "ask"):
            self.assertIn(f"[{name}]", prompt)
        self.assertIn("never spoken", prompt)

    def test_when_on_marks_are_not_spoken_and_cues_reach_the_gesture_client(self):
        with mock.patch.object(script, "GESTURE_CUES", True), \
                mock.patch.object(script.edge_tts, "Communicate", _SpeakingWords):
            self.loop._speak(REPLY)
        text, kwargs = _SpeakingWords.asked[-1]
        self.assertEqual(text, SPOKEN)                                   # no marks in the voice
        self.assertEqual(kwargs, {"boundary": "WordBoundary"})
        self.assertEqual(self.loop.gestures.starts,
                         [{"cues": [{"name": "yes", "time": 1.2}, {"name": "point", "time": 3.1}]}])

    def test_when_on_only_the_first_two_marks_and_one_ask_are_gestured(self):
        # Like what gemma3:12b wrote for "Can you gesture big?": too many marks, [ask] last.
        reply = ("[big] Great answer. [yes] Yes, that is [small] right. "
                 "Look at the [point] diagram on the [ask] board. [ask]")
        with mock.patch.object(script, "GESTURE_CUES", True), \
                mock.patch.object(script.edge_tts, "Communicate", _SpeakingWords):
            self.loop._speak(reply)
        self.assertEqual(_SpeakingWords.asked[-1][0], SPOKEN)            # no mark is spoken
        self.assertEqual(self.loop.gestures.starts,
                         [{"cues": [{"name": "big", "time": 0.1}, {"name": "yes", "time": 1.2},
                                    {"name": "ask", "time": 3.8}]}])

    def test_ask_does_not_count_toward_the_two(self):
        marks = [("ask", 0), ("big", 5), ("small", 9)]
        self.assertEqual(script.limit_cues(marks), marks)

    def test_when_on_a_reply_that_is_only_marks_says_nothing_and_moves_nothing(self):
        before = len(base.tts_calls)
        with mock.patch.object(script, "GESTURE_CUES", True):
            self.loop._speak("[yes] [point]")
        self.assertEqual(len(base.tts_calls), before)                    # nothing sent to the voice
        self.assertEqual(self.loop.gestures.starts, [])
        self.assertFalse(self.loop.speaking.is_set())

    def test_when_on_but_the_voice_gives_no_word_times_it_gestures_as_before(self):
        with mock.patch.object(script, "GESTURE_CUES", True):
            self.loop._speak(REPLY)                                      # stand-in voice: audio only
        self.assertEqual(base.tts_calls[-1][1], SPOKEN)                  # marks still not spoken
        self.assertEqual(self.loop.gestures.starts, [{}])                # plain speech gesture


class AskedForAGesture(unittest.TestCase):
    """Asked to show a gesture, the model is asked for a plain reply and the program puts the gesture on its word."""

    ASKED = ["Show me big.", "Big and small.", "big or small", "Can you show me big and small?",
             "Can you gesture small?", "What gestures can you do?", "Show me a gesture.",
             "Can you point at the board?", "Do the yes gesture.", "Make it small with your hands.",
             "Muéstrame un gesto.", "¿Puedes hacer el gesto de grande y pequeño?"]
    NOT_ASKED = ["What is a robot?", "Is an elephant big or small?", "Tell me a fun fact.",
                 "What does Professor Yutong teach?", "Yes, that makes sense.", "What is the big picture here?",
                 "What's the point of this class?"]

    def setUp(self):
        self.loop = base._new_loop()
        self.loop.gestures = _Gestures()

    def _sent(self, said):
        self.loop._ask_claude(said, "")
        return base.claude_calls[-1]["messages"][-1]["content"]

    def test_requests_for_a_gesture_are_recognized(self):
        for said in self.ASKED:
            with self.subTest(said=said):
                self.assertTrue(script.GESTURE_ASKED.search(said))

    def test_other_questions_are_not(self):
        for said in self.NOT_ASKED:
            with self.subTest(said=said):
                self.assertFalse(script.GESTURE_ASKED.search(said))

    def test_the_hint_goes_with_a_request_when_gestures_are_on(self):
        with mock.patch.object(script, "GESTURE_CUES", True):
            sent = self._sent("Show me big.")
        self.assertIn(script.cue_hint("Show me big."), sent)
        self.assertTrue(sent.endswith("Show me big."))

    def test_no_hint_when_gestures_are_off_or_not_asked_for(self):
        self.assertNotIn(script.CUE_HINT_END, self._sent("Show me big."))
        with mock.patch.object(script, "GESTURE_CUES", True):
            self.assertNotIn(script.CUE_HINT_END, self._sent("What is a robot?"))

    def test_the_hint_shows_no_marks(self):
        # shown marks, Gemma 12B wrote them as words ("This is big big") and made no gesture
        for said in self.ASKED:
            with self.subTest(said=said):
                self.assertEqual(gesture_cues.split(script.cue_hint(said))[1], [])
                self.assertNotIn("[big]", script.cue_hint(said))

    def test_the_hint_names_only_the_gesture_asked_for(self):
        self.assertIn('"Sure! This is big." ', script.cue_hint("Show me big."))
        self.assertIn('"Sure! Yes, exactly!" ', script.cue_hint("Do the yes gesture."))
        self.assertIn('"Sure! Look at the board." ', script.cue_hint("Can you point at the board?"))

    def _cues(self, reply, said):
        return gesture_cues.split(script.add_asked_cues(reply, said))

    def test_the_gesture_asked_for_is_put_on_its_word(self):
        point = script._POINT_CUE
        for said, reply, cues, spoken_word in [
                ("Show me big.", "Sure! This is big.", ["big"], ["big."]),
                ("Can you gesture small?", "Sure! This is small.", ["small"], ["small."]),
                ("Big and small.", "Sure! This is big, and this is small.", ["big", "small"], ["big,", "small."]),
                ("Do the yes gesture.", "Yes, exactly!", ["yes"], ["Yes,"]),
                ("Can you point at the board?", "Sure! Look at the board.", [point], ["board."]),
                ("¿Puedes hacer el gesto de grande y pequeño?", "¡Claro! Esto es grande, y esto es pequeño.",
                 ["big", "small"], ["grande,", "pequeño."]),
                ("Show me a gesture.", "Sure! This is big, and this is small. I can also point at the board.",
                 ["big", "small"], ["big,", "small."])]:
            with self.subTest(said=said):
                spoken, marks = self._cues(reply, said)
                self.assertEqual(spoken, reply)                                 # the words are unchanged
                self.assertEqual([name for name, _ in marks], cues)
                self.assertEqual([spoken[at:].split()[0] for _, at in marks], spoken_word)

    def test_with_no_word_to_land_on_the_gesture_opens_the_reply(self):
        spoken, marks = self._cues("Sure, here it is!", "Do the yes gesture.")
        self.assertEqual((spoken, marks), ("Sure, here it is!", [("yes", 0)]))
        # seen with Gemma 12B: "Sure! [point]" and nothing more
        self.assertEqual(self._cues("Sure! [point]", "Can you point at the board?"),
                         ("Sure!", [(script._POINT_CUE, 0)]))

    def test_with_no_gesture_named_and_no_word_none_is_made(self):
        self.assertEqual(self._cues("Sure, here it is!", "Show me a gesture."), ("Sure, here it is!", []))

    def test_gestures_land_in_the_order_they_are_said(self):
        # seen with Gemma 12B: small said before big
        spoken, marks = self._cues("Sure! [small] This is small. [big] This is big.", "Big and small.")
        self.assertEqual(spoken, "Sure! This is small. This is big.")
        self.assertEqual([(name, spoken[at:].split()[0]) for name, at in marks], [("small", "small."), ("big", "big.")])

    def test_a_mark_used_as_a_word_keeps_its_word(self):
        # seen with Gemma 12B: "Sure! [small] and [big]." was spoken "Sure! and."
        spoken, marks = self._cues("Sure! [small] and [big]. I can also point.", "What gestures can you do?")
        self.assertEqual(spoken, "Sure! small and big. I can also point.")
        self.assertEqual([name for name, _ in marks], ["small", "big"])
        self.assertEqual(self._cues("Sure! Look at the [point] board.", "Can you point at the board?")[0],
                         "Sure! Look at the board.")

    def test_marks_the_model_wrote_are_replaced(self):
        # seen with Gemma 12B: a [small] it added itself to "Show me big"
        self.assertEqual(script.add_asked_cues("Sure! [small] This is big.", "Show me big."),
                         "Sure! This is [big] big.")
        self.assertEqual(script.add_asked_cues("Sure! This is [big] big.", "Show me big."),
                         "Sure! This is [big] big.")
        self.assertEqual(self._cues("Esto es [grande] grande.", "Show me big.")[1], [("big", 8)])

    def test_stage_directions_are_not_spoken(self):
        # seen with Gemma 12B on "Show me a gesture."
        reply = ("Sure! This is [big] big [gesture: arms extended wide], and this is [small] small "
                 "[gesture: hands close together]. I can also point at the board [gesture: arm extends forward].")
        spoken, marks = self._cues(reply, "Show me a gesture.")
        self.assertEqual(spoken, "Sure! This is big, and this is small. I can also point at the board.")
        self.assertEqual([name for name, _ in marks], ["big", "small"])

    def test_the_loop_adds_the_gesture_to_the_reply_it_speaks(self):
        base.reply_text["value"] = "Sure! This is big [gesture: arms wide]."
        try:
            with mock.patch.object(script, "GESTURE_CUES", True):
                reply, _ = self.loop._ask_claude("Show me big.", "")
            self.assertEqual(reply, "Sure! This is [big] big.")
            self.assertEqual(self.loop.history[-1]["content"], "Sure! This is big.")   # history as spoken
            base.reply_text["value"] = "Sure! This is big."
            reply, _ = self.loop._ask_claude("Show me big.", "")                         # gestures off
            self.assertEqual(reply, "Sure! This is big.")
        finally:
            base.reply_text["value"] = "ok"


if __name__ == "__main__":
    unittest.main()
