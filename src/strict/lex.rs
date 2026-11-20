//! Lexer for the S1 strict core (STRICT-CORE §2 grammar). Deliberately its
//! own tiny scanner rather than the Total Grammar lexer: the strict lane must
//! reject, never repair, so it sees only its own token alphabet.

use super::StrictError;

#[derive(Clone, Debug, PartialEq)]
pub enum Tok {
    Ident(String),
    Int(i64),
    Float(f64),
    Str(String),
    Fn,
    Let,
    If,
    Else,
    While,
    Return,
    True,
    False,
    Plus,
    Minus,
    Star,
    Slash,
    Percent,
    PlusW,
    MinusW,
    StarW,
    EqEq,
    NotEq,
    Lt,
    Le,
    Gt,
    Ge,
    Assign,
    LParen,
    RParen,
    LBrace,
    RBrace,
    Comma,
    Colon,
    Arrow,
    Bang,
    Eof,
}

#[derive(Clone, Debug)]
pub struct Token {
    pub tok: Tok,
    pub line: usize,
}

pub fn lex(src: &str) -> Result<Vec<Token>, StrictError> {
    let chars: Vec<char> = src.chars().collect();
    let mut out = Vec::new();
    let mut i = 0usize;
    let mut line = 1usize;
    while i < chars.len() {
        let (tok, next_i, next_line) = lex_one(&chars, i, line)?;
        if let Some(tok) = tok {
            out.push(Token { tok, line });
        }
        if next_line > line {
            line = next_line;
        }
        i = next_i;
    }
    out.push(Token { tok: Tok::Eof, line });
    Ok(out)
}

/// Consumes one token (or whitespace/comment) at `i`; returns
/// (token, next index, line after the token). Comments and whitespace return
/// None so the dispatcher can loop without nesting.
fn lex_one(chars: &[char], i: usize, line: usize) -> Result<(Option<Tok>, usize, usize), StrictError> {
    let c = chars[i];
    match c {
        '\n' => Ok((None, i + 1, line + 1)),
        ' ' | '\t' | '\r' => Ok((None, i + 1, line)),
        '#' => Ok((None, skip_to_eol(chars, i), line)),
        '/' if two_is(chars, i, '/') => Ok((None, skip_to_eol(chars, i), line)),
        '"' => lex_string(chars, i, line),
        _ if c.is_ascii_digit() => lex_number(chars, i, line),
        _ if is_ident_start(c) => lex_word(chars, i, line),
        _ => lex_symbol(chars, i, line),
    }
}

fn is_ident_start(c: char) -> bool {
    c.is_alphabetic() || c == '_'
}

fn is_ident_cont(c: char) -> bool {
    c.is_alphanumeric() || c == '_'
}

fn skip_to_eol(chars: &[char], mut i: usize) -> usize {
    while i < chars.len() && chars[i] != '\n' {
        i += 1;
    }
    i
}

fn two_is(chars: &[char], i: usize, second: char) -> bool {
    i + 1 < chars.len() && chars[i + 1] == second
}

/// The wrapping spellings bind tight: `+w` is one token, while `+ width`
/// stays `+` followed by an identifier.
fn op_letter_follows(chars: &[char], i: usize) -> bool {
    let after = i + 2;
    after >= chars.len() || !is_ident_cont(chars[after])
}

fn lex_string(chars: &[char], mut i: usize, start_line: usize) -> Result<(Option<Tok>, usize, usize), StrictError> {
    i += 1;
    let mut s = String::new();
    let mut line = start_line;
    loop {
        let ch = *chars.get(i).ok_or_else(|| StrictError::new(start_line, "unterminated string literal"))?;
        if ch == '"' {
            return Ok((Some(Tok::Str(s)), i + 1, line));
        }
        if ch == '\\' {
            i = push_escape(chars, i, &mut s, line)?;
            continue;
        }
        if ch == '\n' {
            line += 1;
        }
        s.push(ch);
        i += 1;
    }
}

/// Applies one backslash escape at `i`; returns the index after it. Unknown
/// escapes are rejected: the subset allows only the five C-style ones.
fn push_escape(chars: &[char], i: usize, s: &mut String, line: usize) -> Result<usize, StrictError> {
    let esc = *chars
        .get(i + 1)
        .ok_or_else(|| StrictError::new(line, "unterminated string escape"))?;
    match esc {
        'n' => s.push('\n'),
        't' => s.push('\t'),
        'r' => s.push('\r'),
        '"' => s.push('"'),
        '\\' => s.push('\\'),
        other => {
            let msg = format!("unsupported string escape \\{other} (subset allows \\n \\t \\r \\\" \\\\)");
            return Err(StrictError::new(line, msg));
        }
    }
    Ok(i + 2)
}

fn lex_number(chars: &[char], mut i: usize, line: usize) -> Result<(Option<Tok>, usize, usize), StrictError> {
    let start = i;
    let mut is_float = false;
    while i < chars.len() && (chars[i].is_ascii_digit() || chars[i] == '_') {
        i += 1;
    }
    if i + 1 < chars.len() && chars[i] == '.' && chars[i + 1].is_ascii_digit() {
        is_float = true;
        i += 1;
        while i < chars.len() && (chars[i].is_ascii_digit() || chars[i] == '_') {
            i += 1;
        }
    }
    if let Some(end) = exponent_end(chars, i) {
        is_float = true;
        i = end;
    }
    let text: String = chars[start..i].iter().filter(|c| **c != '_').collect();
    let tok = if is_float {
        let v = text.parse::<f64>().map_err(|_| StrictError::new(line, format!("malformed float literal {text}")))?;
        Tok::Float(v)
    } else {
        let v = text
            .parse::<i64>()
            .map_err(|_| StrictError::new(line, format!("integer literal {text} out of the checked 64-bit range")))?;
        Tok::Int(v)
    };
    Ok((Some(tok), i, line))
}

/// `e`/`E` starts an exponent only when followed by an optional sign and at
/// least one digit; otherwise it is the start of the next identifier.
fn exponent_end(chars: &[char], i: usize) -> Option<usize> {
    if i >= chars.len() || (chars[i] != 'e' && chars[i] != 'E') {
        return None;
    }
    let mut j = i + 1;
    if j < chars.len() && (chars[j] == '+' || chars[j] == '-') {
        j += 1;
    }
    if j < chars.len() && chars[j].is_ascii_digit() {
        while j < chars.len() && chars[j].is_ascii_digit() {
            j += 1;
        }
        return Some(j);
    }
    None
}

fn lex_word(chars: &[char], mut i: usize, line: usize) -> Result<(Option<Tok>, usize, usize), StrictError> {
    let start = i;
    while i < chars.len() && is_ident_cont(chars[i]) {
        i += 1;
    }
    let word: String = chars[start..i].iter().collect();
    let tok = match word.as_str() {
        "fn" => Tok::Fn,
        "let" => Tok::Let,
        "if" => Tok::If,
        "else" => Tok::Else,
        "while" => Tok::While,
        "return" => Tok::Return,
        "true" => Tok::True,
        "false" => Tok::False,
        _ => Tok::Ident(word),
    };
    Ok((Some(tok), i, line))
}

fn lex_symbol(chars: &[char], i: usize, line: usize) -> Result<(Option<Tok>, usize, usize), StrictError> {
    if let Some((tok, width)) = lex_two_char(chars, i) {
        return Ok((Some(tok), i + width, line));
    }
    if let Some((tok, width)) = lex_bracket(chars[i]) {
        return Ok((Some(tok), i + width, line));
    }
    if let Some((tok, width)) = lex_op(chars[i]) {
        return Ok((Some(tok), i + width, line));
    }
    Err(StrictError::new(
        line,
        format!("unexpected character {:?} — outside the strict-core grammar", chars[i]),
    ))
}

/// Brackets and punctuation: always single-character tokens.
fn lex_bracket(c: char) -> Option<(Tok, usize)> {
    let tok = match c {
        '(' => Tok::LParen,
        ')' => Tok::RParen,
        '{' => Tok::LBrace,
        '}' => Tok::RBrace,
        ',' => Tok::Comma,
        ':' => Tok::Colon,
        _ => return None,
    };
    Some((tok, 1))
}

/// Arithmetic, comparison and negation single-character operators.
fn lex_op(c: char) -> Option<(Tok, usize)> {
    let tok = match c {
        '+' => Tok::Plus,
        '-' => Tok::Minus,
        '*' => Tok::Star,
        '/' => Tok::Slash,
        '%' => Tok::Percent,
        '<' => Tok::Lt,
        '>' => Tok::Gt,
        '=' => Tok::Assign,
        '!' => Tok::Bang,
        _ => return None,
    };
    Some((tok, 1))
}

fn single(tok: Tok, i: usize, line: usize) -> Result<(Option<Tok>, usize, usize), StrictError> {
    Ok((Some(tok), i + 1, line))
}

fn lex_two_char(chars: &[char], i: usize) -> Option<(Tok, usize)> {
    if i + 1 >= chars.len() {
        return None;
    }
    let (a, b) = (chars[i], chars[i + 1]);
    let tok = match (a, b) {
        ('+', 'w') if op_letter_follows(chars, i) => Tok::PlusW,
        ('-', 'w') if op_letter_follows(chars, i) => Tok::MinusW,
        ('*', 'w') if op_letter_follows(chars, i) => Tok::StarW,
        ('-', '>') => Tok::Arrow,
        ('=', '=') => Tok::EqEq,
        ('!', '=') => Tok::NotEq,
        ('<', '=') => Tok::Le,
        ('>', '=') => Tok::Ge,
        _ => return None,
    };
    Some((tok, 2))
}
