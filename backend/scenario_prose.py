"""Punctuation for public scenario preambles, shared by HTML and Word."""
import re


def join_scope_notes(notes):
    sentences = []
    for note in notes or []:
        text = note.strip().rstrip(';；,，:：').rstrip()
        if not text:
            continue
        if not re.search(r'''[。.!?！？…][”’"')）\]】]*$''', text):
            text += '。'
        sentences.append(text)
    return ''.join(sentences)
