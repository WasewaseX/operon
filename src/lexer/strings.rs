//! lexer/strings.rs, string-like literals: W030 raw strings, W029 byte
//! strings, multiline triple-quoted strings, quoted strings with `{..}`
//! interpolation detection, and the single-quote repair.


use super::scan::Lexer;
use super::Tok;

impl Lexer {
    /// Claim the cursor when it sits on any string-like opener; dispatch
    /// per class. Returns false when the char opens no literal.
    pub(super) fn scan_stringlike(&mut self) -> bool {
        let c = self.chars[self.i];
        if c == 'r' && self.i + 1 < self.n && self.chars[self.i + 1] == '"' {
            self.scan_raw_string();
            return true;
        }
        if (c == 'b' || c == 'B') && self.i + 1 < self.n && matches!(self.chars[self.i + 1], '"' | '\'')
        {
            self.scan_bytes_string();
            return true;
        }
        if c == '"' && self.i + 2 < self.n && self.chars[self.i + 1] == '"' && self.chars[self.i + 2] == '"'
        {
            self.scan_triple_string();
            return true;
        }
        if c == '"' {
            self.scan_quoted_string('"', true);
            return true;
        }
        if c == '\'' {
            // single-quote string -> wobble: treat as double-quoted (rung 4)
            self.note_r4("single-quoted string repaired to double quotes");
            // the repaired form drops lex_string's own unclosed note (the
            // repair note above is the diagnosis that survives)
            self.scan_quoted_string('\'', false);
            return true;
        }
        false
    }

    /// W030: raw strings r"...", no escapes, no interpolation; ends at
    /// the closing quote (newlines allowed; the raw content is verbatim).
    /// A bare `r` identifier that is NOT followed by a quote is untouched.
    fn scan_raw_string(&mut self) {
        self.i += 2; // skip r"
        let mut raw = String::new();
        let mut closed = false;
        while self.i < self.n {
            if self.chars[self.i] == '"' {
                self.i += 1;
                closed = true;
                break;
            }
            if self.chars[self.i] == '\n' {
                self.line += 1;
            }
            raw.push(self.chars[self.i]);
            self.i += 1;
        }
        if !closed {
            self.note_r4("unclosed raw string consumed to end of input");
        }
        self.push(Tok::Str(raw));
    }

    /// W029: byte strings b"..." / b'...', bytes literals. Escape set:
    /// \n \t \r \\ \" \' \0 \xNN (exactly two hex digits); unknown escapes
    /// keep the backslash + char verbatim (Python bytes convention); no
    /// interpolation ever ({ and } are plain bytes). A non-ASCII source
    /// char is UTF-8 encoded with a note (Total Grammar: repair, never
    /// reject). Unclosed literals consume to end of input with a note.
    fn scan_bytes_string(&mut self) {
        let quote = self.chars[self.i + 1];
        if quote == '\'' {
            self.note_r4("single-quoted bytes literal repaired to double quotes");
        }
        self.i += 2; // skip b + quote
        let mut out: Vec<u8> = Vec::new();
        let mut closed = false;
        while self.i < self.n {
            if self.chars[self.i] == quote {
                self.i += 1;
                closed = true;
                break;
            }
            if self.chars[self.i] == '\\' && self.i + 1 < self.n {
                let e = self.chars[self.i + 1];
                self.bytes_escape(e, &mut out);
                continue;
            }
            if self.chars[self.i] == '\n' {
                self.line += 1;
            }
            let ch = self.chars[self.i];
            if ch as u32 > 127 {
                // non-ASCII: UTF-8 encode the char (repair-with-note)
                let mut buf = [0u8; 4];
                for byte in ch.encode_utf8(&mut buf).as_bytes() {
                    out.push(*byte);
                }
                self.note_r4("non-ASCII char in bytes literal encoded as UTF-8");
            } else {
                out.push(ch as u8);
            }
            self.i += 1;
        }
        if !closed {
            self.note_r4("unclosed bytes literal consumed to end of input");
        }
        self.push(Tok::Bytes(out));
    }

    /// One bytes-literal escape: consume 2 chars (or 4 for a valid \xNN)
    /// and push the produced bytes; malformed keeps the text verbatim
    /// (with a note) instead of rejecting the program.
    fn bytes_escape(&mut self, e: char, out: &mut Vec<u8>) {
        match e {
            'n' => out.push(b'\n'),
            't' => out.push(b'\t'),
            'r' => out.push(b'\r'),
            '0' => out.push(0),
            '\\' => out.push(b'\\'),
            '"' => out.push(b'"'),
            '\'' => out.push(b'\''),
            'x' => {
                let hex = |ch: char| ch.is_ascii_hexdigit();
                if self.i + 3 < self.n && hex(self.chars[self.i + 2]) && hex(self.chars[self.i + 3])
                {
                    let hi = self.chars[self.i + 2].to_digit(16).unwrap_or(0) as u8;
                    let lo = self.chars[self.i + 3].to_digit(16).unwrap_or(0) as u8;
                    out.push(hi * 16 + lo);
                    self.i += 4;
                    return;
                }
                self.note_r4("malformed \\x escape in bytes literal kept verbatim");
                out.push(b'\\');
                out.push(b'x');
            }
            _ => {
                out.push(b'\\');
                // UTF-8-encode the escaped char (parity with the
                // oracle mirror; ASCII chars are 1 byte anyway)
                let mut buf = [0u8; 4];
                for byte in e.encode_utf8(&mut buf).as_bytes() {
                    out.push(*byte);
                }
            }
        }
        self.i += 2;
    }

    /// W030: multiline triple-quoted strings """...""", escapes and
    /// interpolation still processed; content is verbatim (no implicit
    /// indent stripping); can contain single/double quotes freely.
    fn scan_triple_string(&mut self) {
        self.i += 3; // skip """
        let mut raw = String::new();
        let mut closed = false;
        while self.i < self.n {
            if self.chars[self.i] == '"'
                && self.i + 2 < self.n
                && self.chars[self.i + 1] == '"'
                && self.chars[self.i + 2] == '"'
            {
                self.i += 3;
                closed = true;
                break;
            }
            if self.chars[self.i] == '\\' && self.i + 1 < self.n {
                // same escape set as lex_string
                let e = self.chars[self.i + 1];
                push_triple_escape(&mut raw, e);
                self.i += 2;
                continue;
            }
            if self.chars[self.i] == '\n' {
                self.line += 1;
            }
            raw.push(self.chars[self.i]);
            self.i += 1;
        }
        if !closed {
            self.note_r4("unclosed multiline string consumed to end of input");
        }
        // interpolation: {..} parts present? mark as Interp for the parser
        self.push(if has_interp_parts(&raw) {
            Tok::Interp(raw)
        } else {
            Tok::Str(raw)
        });
    }

    /// Quoted string via lex_string; the unclosed-literal note (when kept)
    /// rides the closing line, the token rides the line after the scan
    /// (unchanged from the pre-split single-pass order).
    fn scan_quoted_string(&mut self, quote: char, emit_close_note: bool) {
        let (tok, note) = lex_string(&self.chars, &mut self.i, &mut self.line, quote);
        if emit_close_note {
            if let Some(msg) = note {
                self.note_r4(msg);
            }
        }
        self.push(tok);
    }
}

/// One triple-string escape (same set as lex_string).
fn push_triple_escape(raw: &mut String, e: char) {
    match e {
        'n' => raw.push('\n'),
        't' => raw.push('\t'),
        '\\' => raw.push('\\'),
        '"' => raw.push('"'),
        '{' => raw.push('{'),
        '}' => raw.push('}'),
        other => {
            raw.push('\\');
            raw.push(other);
        }
    }
}

/// Interpolation detection for triple-quoted strings: any `{` seen.
fn has_interp_parts(raw: &str) -> bool {
    let mut depth = 0usize;
    let mut any = false;
    for ch in raw.chars() {
        match ch {
            '{' => {
                depth += 1;
                any = true;
            }
            '}' => {
                depth = depth.saturating_sub(1);
            }
            _ => {}
        }
    }
    any
}

/// Lex a double-quoted (or repaired single-quoted) string starting at the
/// opening quote. Handles escapes; returns Interp token if {..} parts exist.
fn lex_string(chars: &[char], i: &mut usize, line: &mut usize, quote: char) -> (Tok, Option<String>) {
    let n = chars.len();
    *i += 1; // skip opening quote
    let mut raw = String::new();
    let mut closed = false;
    let mut has_interp = false;
    let mut depth = 0usize;
    while *i < n {
        let c = chars[*i];
        if c == '\n' {
            *line += 1;
            raw.push('\n');
            *i += 1;
            continue;
        }
        if c == '\\' && *i + 1 < n {
            let e = chars[*i + 1];
            match e {
                'n' => raw.push('\n'),
                't' => raw.push('\t'),
                '\\' => raw.push('\\'),
                '"' => raw.push('"'),
                '{' => raw.push('{'),
                '}' => raw.push('}'),
                other => {
                    raw.push('\\');
                    raw.push(other);
                }
            }
            *i += 2;
            continue;
        }
        if depth == 0 && c == quote {
            *i += 1;
            closed = true;
            break;
        }
        if c == '{' {
            depth += 1;
            has_interp = true;
        }
        if c == '}' && depth > 0 {
            depth -= 1;
        }
        raw.push(c);
        *i += 1;
    }
    let note = if closed {
        None
    } else {
        Some("unclosed string consumed to end of file".to_string())
    };
    let tok = if has_interp {
        Tok::Interp(raw)
    } else {
        Tok::Str(raw)
    };
    (tok, note)
}
