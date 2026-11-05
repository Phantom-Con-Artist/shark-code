use crate::{Engine, Error, Result, digest};
use serde::{Deserialize, Serialize};
use tree_sitter::{Node, Parser};

#[derive(Debug, Serialize, Deserialize)]
pub struct Outline {
    pub path: String,
    pub version: String,
    pub artifact_id: String,
    pub language: String,
    pub symbols: Vec<Symbol>,
    pub imports: Vec<ImportSite>,
    pub syntax_errors: bool,
    pub truncated: bool,
    pub cache_hit: bool,
}
#[derive(Debug, Serialize, Deserialize)]
pub struct Symbol {
    pub name: String,
    pub qualified_name: String,
    pub kind: String,
    pub start_byte: usize,
    pub end_byte: usize,
    pub start_line: usize,
    pub end_line: usize,
    pub calls: Vec<CallSite>,
    pub calls_truncated: bool,
}
#[derive(Debug, Serialize, Deserialize)]
pub struct CallSite {
    pub expression: String,
    pub line: usize,
    pub resolution: String,
}
#[derive(Debug, Serialize, Deserialize)]
pub struct ImportSite {
    pub source: String,
    pub line: usize,
    pub resolution: String,
}
impl Engine {
    pub fn outline(&self, path: &str) -> Result<Outline> {
        let source = self.text(path)?;
        let version = digest(&source);
        let extension = path.rsplit('.').next().unwrap_or("");
        let (language, grammar) = match extension {
            "ts" => (
                "typescript",
                tree_sitter_typescript::LANGUAGE_TYPESCRIPT.into(),
            ),
            "tsx" => ("tsx", tree_sitter_typescript::LANGUAGE_TSX.into()),
            "js" | "jsx" | "mjs" | "cjs" => ("javascript", tree_sitter_javascript::LANGUAGE.into()),
            "rs" => ("rust", tree_sitter_rust::LANGUAGE.into()),
            _ => {
                return Err(Error::new(
                    "unsupported_language",
                    "Outlines currently support TypeScript, TSX, JavaScript and Rust",
                ));
            }
        };
        let key = digest(&format!(
            "outline:v1:{}:{path}:{version}:{language}",
            env!("CARGO_PKG_VERSION")
        ));
        if let Some(mut outline) = self.cached::<Outline>(&key)? {
            outline.cache_hit = true;
            return Ok(outline);
        }
        let mut parser = Parser::new();
        parser
            .set_language(&grammar)
            .map_err(|e| Error::new("parser_error", e.to_string()))?;
        let tree = parser
            .parse(&source, None)
            .ok_or_else(|| Error::new("parser_error", "Parsing did not finish"))?;
        let artifact_id = format!("source-{version}");
        self.put_artifact(&artifact_id, &source)?;
        let mut outline = Outline {
            path: path.into(),
            version,
            artifact_id,
            language: language.into(),
            symbols: vec![],
            imports: vec![],
            syntax_errors: tree.root_node().has_error(),
            truncated: false,
            cache_hit: false,
        };
        walk(tree.root_node(), &source, "", &mut outline, 0);
        while serde_json::to_vec(&outline)?.len() > crate::workspace::MAX_RESPONSE_BYTES {
            outline.truncated = true;
            if outline.symbols.pop().is_none() && outline.imports.pop().is_none() {
                break;
            }
        }
        self.cache(&key, &outline)?;
        Ok(outline)
    }
}
fn text<'a>(node: Node, source: &'a str) -> &'a str {
    &source[node.byte_range()]
}
fn symbol_kind(node: Node) -> bool {
    matches!(
        node.kind(),
        "function_declaration"
            | "function_item"
            | "class_declaration"
            | "method_definition"
            | "interface_declaration"
            | "type_alias_declaration"
            | "enum_declaration"
            | "struct_item"
            | "enum_item"
            | "trait_item"
            | "type_item"
    ) || (node.kind() == "variable_declarator"
        && node
            .child_by_field_name("value")
            .is_some_and(|v| matches!(v.kind(), "arrow_function" | "function_expression")))
}
fn walk(node: Node, source: &str, scope: &str, result: &mut Outline, depth: usize) {
    if depth > 100 {
        result.truncated = true;
        return;
    }
    let mut next_scope = scope.to_owned();
    if symbol_kind(node) {
        if result.symbols.len() >= 200 {
            result.truncated = true;
            return;
        }
        if let Some(name) = node.child_by_field_name("name") {
            let name: String = text(name, source).chars().take(200).collect();
            let qualified_name = if scope.is_empty() {
                name.clone()
            } else {
                format!("{scope}::{name}")
            };
            let mut calls = vec![];
            collect_calls(node, node.id(), source, &mut calls, 0);
            let calls_truncated = calls.len() > 100;
            calls.truncate(100);
            result.symbols.push(Symbol {
                name,
                qualified_name: qualified_name.clone(),
                kind: node.kind().into(),
                start_byte: node.start_byte(),
                end_byte: node.end_byte(),
                start_line: node.start_position().row + 1,
                end_line: node.end_position().row + 1,
                calls,
                calls_truncated,
            });
            next_scope = qualified_name;
        }
    } else if node.kind() == "impl_item"
        && let Some(kind) = node.child_by_field_name("type")
    {
        next_scope = text(kind, source).to_string();
    }
    if matches!(
        node.kind(),
        "import_statement" | "use_declaration" | "mod_item" | "export_statement"
    ) {
        let dependency = node.child_by_field_name("source").or_else(|| {
            if node.kind() == "use_declaration" {
                node.child_by_field_name("argument")
            } else {
                None
            }
        });
        if let Some(dependency) = dependency {
            if result.imports.len() < 100 {
                result.imports.push(ImportSite {
                    source: text(dependency, source)
                        .trim_matches(['\'', '"'])
                        .chars()
                        .take(300)
                        .collect(),
                    line: node.start_position().row + 1,
                    resolution: "unresolved_syntax".into(),
                });
            } else {
                result.truncated = true;
            }
        }
    }
    let mut cursor = node.walk();
    for child in node.named_children(&mut cursor) {
        walk(child, source, &next_scope, result, depth + 1);
    }
}
fn collect_calls(node: Node, root: usize, source: &str, result: &mut Vec<CallSite>, depth: usize) {
    if depth > 100 || result.len() > 100 {
        return;
    }
    if node.id() != root && symbol_kind(node) {
        return;
    }
    if node.kind() == "call_expression"
        && let Some(callee) = node.child_by_field_name("function")
    {
        result.push(CallSite {
            expression: text(callee, source).chars().take(200).collect(),
            line: node.start_position().row + 1,
            resolution: "unresolved_syntax".into(),
        });
    }
    let mut cursor = node.walk();
    for child in node.named_children(&mut cursor) {
        collect_calls(child, root, source, result, depth + 1);
    }
}
