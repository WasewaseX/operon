//! Expression parsing for the S1 strict core (STRICT-CORE §2.3): comparison
//! is non-associative, additive/multiplicative chains are left-associative.
//! The §2.3 grammar has NO logic-operator productions; they arrive by spec
//! amendment, not silently.

use super::StrictError;
use super::ast::Expr;
use super::lex::Tok;
use super::parse::{Parser, LEGACY_CONSTRUCTS, LEGACY_FN_SYNONYMS};
use crate::mir::BinOp;

impl Parser {
    // comparison := additive ((== | != | < | <= | > | >=) additive)?
    pub fn parse_expr(&mut self) -> Result<Expr, StrictError> {
        let lhs = self.parse_additive()?;
        let op = match self.peek() {
            Tok::EqEq => BinOp::Eq,
            Tok::NotEq => BinOp::Ne,
            Tok::Lt => BinOp::Lt,
            Tok::Le => BinOp::Le,
            Tok::Gt => BinOp::Gt,
            Tok::Ge => BinOp::Ge,
            _ => return Ok(lhs),
        };
        let line = self.bump().line;
        let rhs = self.parse_additive()?;
        Ok(Expr::Bin(op, Box::new(lhs), Box::new(rhs), line))
    }

    // additive := multiplicative ((+ | - | +w | -w) multiplicative)*
    pub fn parse_additive(&mut self) -> Result<Expr, StrictError> {
        let mut lhs = self.parse_multiplicative()?;
        loop {
            let op = match self.peek() {
                Tok::Plus => BinOp::Add,
                Tok::Minus => BinOp::Sub,
                Tok::PlusW => BinOp::AddWrap,
                Tok::MinusW => BinOp::SubWrap,
                _ => return Ok(lhs),
            };
            let line = self.bump().line;
            let rhs = self.parse_multiplicative()?;
            lhs = Expr::Bin(op, Box::new(lhs), Box::new(rhs), line);
        }
    }

    // multiplicative := unary ((* | / | % | *w) unary)*
    fn parse_multiplicative(&mut self) -> Result<Expr, StrictError> {
        let mut lhs = self.parse_unary()?;
        loop {
            let op = match self.peek() {
                Tok::Star => BinOp::Mul,
                Tok::Slash => BinOp::Div,
                Tok::Percent => BinOp::Rem,
                Tok::StarW => BinOp::MulWrap,
                _ => return Ok(lhs),
            };
            let line = self.bump().line;
            let rhs = self.parse_unary()?;
            lhs = Expr::Bin(op, Box::new(lhs), Box::new(rhs), line);
        }
    }

    fn parse_unary(&mut self) -> Result<Expr, StrictError> {
        let line = self.line();
        match self.peek() {
            Tok::Minus => {
                self.bump();
                let v = self.parse_unary()?;
                Ok(Expr::Unary(crate::mir::UnOp::Neg, Box::new(v), line))
            }
            Tok::Bang => {
                self.bump();
                let v = self.parse_unary()?;
                Ok(Expr::Unary(crate::mir::UnOp::Not, Box::new(v), line))
            }
            _ => self.parse_primary(),
        }
    }

    fn parse_primary(&mut self) -> Result<Expr, StrictError> {
        let line = self.line();
        match self.bump().tok.clone() {
            Tok::Int(v) => Ok(Expr::Int(v, line)),
            Tok::Float(v) => Ok(Expr::Float(v, line)),
            Tok::True => Ok(Expr::Bool(true, line)),
            Tok::False => Ok(Expr::Bool(false, line)),
            Tok::Str(s) => Ok(Expr::Str(s, line)),
            Tok::Ident(name) if LEGACY_FN_SYNONYMS.contains(&name.as_str()) => {
                Err(StrictError::new(
                    line,
                    format!("legacy function keyword '{name}' — strict core uses fn (STRICT-CORE §2.1)"),
                ))
            }
            Tok::Ident(name) if LEGACY_CONSTRUCTS.contains(&name.as_str()) => {
                Err(StrictError::new(
                    line,
                    format!("'{name}' is outside the strict core (see docs/design/STRICT-CORE.md §2.5)"),
                ))
            }
            Tok::Ident(name) => self.parse_ident_tail(name, line),
            Tok::LParen => {
                let e = self.parse_expr()?;
                self.expect(&Tok::RParen, "`)`")?;
                Ok(e)
            }
            _ => Err(self.unexpected("an expression (literal | identifier | call | unary | parenthesized)")),
        }
    }

    /// After an identifier: `(` starts a call, anything else is a plain
    /// variable read.
    fn parse_ident_tail(&mut self, name: String, line: usize) -> Result<Expr, StrictError> {
        if *self.peek() != Tok::LParen {
            return Ok(Expr::Ident(name, line));
        }
        self.bump();
        let args = self.parse_call_args()?;
        self.expect(&Tok::RParen, "`)` after the call arguments")?;
        Ok(Expr::Call(name, args, line))
    }

    fn parse_call_args(&mut self) -> Result<Vec<Expr>, StrictError> {
        let mut args = Vec::new();
        if *self.peek() == Tok::RParen {
            return Ok(args);
        }
        loop {
            args.push(self.parse_expr()?);
            if *self.peek() != Tok::Comma {
                return Ok(args);
            }
            self.bump();
        }
    }
}
