use serde_json::{Value, json};
use std::{
    io::Write,
    process::{Command, Stdio},
};
#[test]
fn real_process_frames_errors_and_caches_results() {
    let directory = tempfile::TempDir::new().unwrap();
    std::fs::write(directory.path().join("a.ts"), "export function old() {}\n").unwrap();
    let mut child = Command::new(env!("CARGO_BIN_EXE_shark-backend"))
        .args(["--workspace", directory.path().to_str().unwrap()])
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .unwrap();
    let requests = [
        "not json".to_owned(),
        json!({"id":"cap","method":"capabilities"}).to_string(),
        json!({"id":1,"method":"code/outline","params":{"path":"a.ts"}}).to_string(),
        json!({"id":2,"method":"code/outline","params":{"path":"a.ts"}}).to_string(),
        json!({"id":3,"method":"file/read","params":{"path":"a.ts"}}).to_string(),
        json!({"id":4,"method":"cache/stats"}).to_string(),
    ];
    {
        let input = child.stdin.as_mut().unwrap();
        for request in requests {
            writeln!(input, "{request}").unwrap();
        }
    }
    drop(child.stdin.take());
    let output = child.wait_with_output().unwrap();
    assert!(output.status.success());
    assert!(output.stderr.is_empty());
    let responses: Vec<Value> = String::from_utf8(output.stdout)
        .unwrap()
        .lines()
        .map(|line| serde_json::from_str(line).unwrap())
        .collect();
    assert_eq!(responses.len(), 6);
    assert_eq!(responses[0]["error"]["code"], "invalid_request");
    assert_eq!(responses[1]["id"], "cap");
    assert_eq!(
        responses[1]["result"]["analysis"]["resolution"],
        "syntax_only"
    );
    assert_eq!(responses[2]["result"]["cache_hit"], false);
    assert_eq!(responses[3]["result"]["cache_hit"], true);
    assert_eq!(responses[5]["result"]["hits"], 1);
}
#[test]
fn oversized_request_does_not_break_the_following_request() {
    let directory = tempfile::TempDir::new().unwrap();
    let mut child = Command::new(env!("CARGO_BIN_EXE_shark-backend"))
        .args(["--workspace", directory.path().to_str().unwrap()])
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .unwrap();
    let mut stdin = child.stdin.take().unwrap();
    let writer = std::thread::spawn(move || {
        stdin.write_all(&vec![b' '; 8 * 1024 * 1024 + 1]).unwrap();
        stdin
            .write_all(b"\n{\"id\":2,\"method\":\"capabilities\"}\n")
            .unwrap();
    });
    let output = child.wait_with_output().unwrap();
    writer.join().unwrap();
    assert!(output.status.success());
    let values: Vec<Value> = String::from_utf8(output.stdout)
        .unwrap()
        .lines()
        .map(|line| serde_json::from_str(line).unwrap())
        .collect();
    assert_eq!(values[0]["error"]["code"], "request_too_large");
    assert_eq!(values[1]["id"], 2);
}
#[test]
fn proposal_apply_and_undo_work_across_process_restarts() {
    fn request(path: &std::path::Path, request: Value) -> Value {
        let mut child = Command::new(env!("CARGO_BIN_EXE_shark-backend"))
            .args(["--workspace", path.to_str().unwrap()])
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()
            .unwrap();
        writeln!(child.stdin.take().unwrap(), "{request}").unwrap();
        let output = child.wait_with_output().unwrap();
        assert!(output.status.success());
        serde_json::from_slice(&output.stdout).unwrap()
    }
    let directory = tempfile::TempDir::new().unwrap();
    std::fs::write(directory.path().join("a.ts"), "export const old = 1;\n").unwrap();
    let read = request(
        directory.path(),
        json!({"id":1,"method":"file/read","params":{"path":"a.ts"}}),
    );
    let proposal = request(
        directory.path(),
        json!({"id":2,"method":"changes/preview","params":{"changes":[
            {"kind":"edit","path":"a.ts","expected_version":read["result"]["version"],"edits":[{"kind":"replace","old":"old","new":"renamed"}]},
            {"kind":"create","path":"b.ts","content":"export { renamed } from './a';\n"}
        ]}}),
    );
    assert_eq!(proposal["result"]["status"], "prepared");
    let id = proposal["result"]["id"].as_str().unwrap();
    assert_eq!(
        request(
            directory.path(),
            json!({"id":3,"method":"changes/apply","params":{"id":id}})
        )["result"]["status"],
        "applied"
    );
    assert!(
        std::fs::read_to_string(directory.path().join("a.ts"))
            .unwrap()
            .contains("renamed")
    );
    assert!(directory.path().join("b.ts").exists());
    assert_eq!(
        request(
            directory.path(),
            json!({"id":4,"method":"changes/revert","params":{"id":id}})
        )["result"]["status"],
        "reverted"
    );
    assert!(!directory.path().join("b.ts").exists());
    assert_eq!(
        std::fs::read_to_string(directory.path().join("a.ts")).unwrap(),
        "export const old = 1;\n"
    );
}
