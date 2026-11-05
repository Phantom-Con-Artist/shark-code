use shark_core::{Change, ChangeSet, Edit, Engine, digest};
use std::fs;
use tempfile::TempDir;
fn fixture() -> (TempDir, Engine) {
    let dir = TempDir::new().unwrap();
    let engine = Engine::open(dir.path()).unwrap();
    (dir, engine)
}
fn edit(path: &str, old: &str, new: &str, version: &str) -> Change {
    Change::Edit {
        path: path.into(),
        expected_version: version.into(),
        edits: vec![Edit::Replace {
            old: old.into(),
            new: new.into(),
            expected_matches: 1,
        }],
    }
}
#[test]
fn cache_reuses_exact_source_and_invalidates_external_changes() {
    let (dir, engine) = fixture();
    fs::write(dir.path().join("a.ts"), "export function old() {}\n").unwrap();
    let first = engine.outline("a.ts").unwrap();
    assert!(!first.cache_hit);
    assert!(engine.outline("a.ts").unwrap().cache_hit);
    // Same byte length: mtime/size-only caches would be unsafe.
    fs::write(dir.path().join("a.ts"), "export function new() {}\n").unwrap();
    let updated = engine.outline("a.ts").unwrap();
    assert!(!updated.cache_hit);
    assert_ne!(first.version, updated.version);
    assert_eq!(updated.symbols[0].name, "new");
    let reopened = Engine::open(dir.path()).unwrap();
    assert!(reopened.outline("a.ts").unwrap().cache_hit);
    let old = engine.artifact_read(&first.artifact_id, 1, 20).unwrap();
    assert!(old.content.contains("old"));
    assert_eq!(old.path, "historical artifact");
}
#[test]
fn multi_file_changes_preview_apply_and_revert_preserve_exact_bytes() {
    let (dir, engine) = fixture();
    let a = "const one = 1;\r\nconst kept = 2;\r\n";
    let b = "export { one } from './a';\n";
    fs::write(dir.path().join("a.ts"), a).unwrap();
    fs::write(dir.path().join("b.ts"), b).unwrap();
    let preview = engine
        .preview(ChangeSet {
            changes: vec![
                edit("a.ts", "one", "first", &digest(a)),
                edit("b.ts", "one", "first", &digest(b)),
                Change::Create {
                    path: "nested/new.ts".into(),
                    content: "export {};\n".into(),
                },
            ],
        })
        .unwrap();
    assert_eq!(
        fs::read_to_string(dir.path().join("a.ts")).unwrap(),
        a,
        "Preview cannot edit source"
    );
    assert_eq!(engine.apply(&preview.id).unwrap().status, "applied");
    assert_eq!(
        fs::read_to_string(dir.path().join("a.ts")).unwrap(),
        "const first = 1;\r\nconst kept = 2;\r\n"
    );
    assert!(dir.path().join("nested/new.ts").exists());
    assert_eq!(engine.revert(&preview.id).unwrap().status, "reverted");
    assert_eq!(fs::read_to_string(dir.path().join("a.ts")).unwrap(), a);
    assert_eq!(fs::read_to_string(dir.path().join("b.ts")).unwrap(), b);
    assert!(!dir.path().join("nested/new.ts").exists());
    assert!(
        engine.apply(&preview.id).is_err(),
        "A journal cannot be reapplied"
    );
}
#[test]
fn stale_second_file_prevents_all_writes_and_revert_respects_human_edits() {
    let (dir, engine) = fixture();
    for path in ["a.ts", "b.ts"] {
        fs::write(dir.path().join(path), "old").unwrap();
    }
    let preview = engine
        .preview(ChangeSet {
            changes: vec![
                edit("a.ts", "old", "new", &digest("old")),
                edit("b.ts", "old", "new", &digest("old")),
            ],
        })
        .unwrap();
    fs::write(dir.path().join("b.ts"), "human").unwrap();
    assert_eq!(
        engine.apply(&preview.id).unwrap_err().code,
        "version_conflict"
    );
    assert_eq!(fs::read_to_string(dir.path().join("a.ts")).unwrap(), "old");
    fs::write(dir.path().join("b.ts"), "old").unwrap();
    engine.apply(&preview.id).unwrap();
    fs::write(dir.path().join("b.ts"), "another human edit").unwrap();
    assert_eq!(
        engine.revert(&preview.id).unwrap_err().code,
        "version_conflict"
    );
    assert_eq!(fs::read_to_string(dir.path().join("a.ts")).unwrap(), "new");
}
#[test]
fn ambiguous_and_overlapping_edits_are_rejected() {
    let (dir, engine) = fixture();
    fs::write(dir.path().join("a.ts"), "aaa aaa").unwrap();
    let err = engine
        .preview(ChangeSet {
            changes: vec![edit("a.ts", "aaa", "b", &digest("aaa aaa"))],
        })
        .unwrap_err();
    assert_eq!(err.code, "ambiguous_edit");
    let edits = vec![
        Edit::Range {
            start_byte: 0,
            end_byte: 3,
            old: "aaa".into(),
            new: "b".into(),
        },
        Edit::Range {
            start_byte: 1,
            end_byte: 2,
            old: "a".into(),
            new: "x".into(),
        },
    ];
    assert_eq!(
        engine
            .preview(ChangeSet {
                changes: vec![Change::Edit {
                    path: "a.ts".into(),
                    expected_version: digest("aaa aaa"),
                    edits
                }]
            })
            .unwrap_err()
            .code,
        "overlapping_edits"
    );
}
#[test]
fn utf8_ranges_and_duplicate_aliases_are_checked() {
    let (dir, engine) = fixture();
    fs::write(dir.path().join("a.ts"), "é").unwrap();
    let edits = vec![Edit::Range {
        start_byte: 0,
        end_byte: 1,
        old: "é".into(),
        new: "e".into(),
    }];
    assert_eq!(
        engine
            .preview(ChangeSet {
                changes: vec![Change::Edit {
                    path: "a.ts".into(),
                    expected_version: digest("é"),
                    edits
                }]
            })
            .unwrap_err()
            .code,
        "invalid_range"
    );
    for path in [
        "../a",
        "/etc/passwd",
        ".git/config",
        ".shark/cache/a",
        "a//b",
        "a/./b",
        "",
    ] {
        assert!(engine.read(path, 1, 20).is_err(), "{path}");
    }
}
#[test]
fn interrupted_apply_recovery_does_not_lose_external_edits() {
    let (dir, engine) = fixture();
    fs::write(dir.path().join("a.ts"), "old").unwrap();
    let preview = engine
        .preview(ChangeSet {
            changes: vec![edit("a.ts", "old", "new", &digest("old"))],
        })
        .unwrap();
    let journal_path = dir
        .path()
        .join(format!(".shark/journals/{}.json", preview.id));
    let mut journal: serde_json::Value =
        serde_json::from_slice(&fs::read(&journal_path).unwrap()).unwrap();
    journal["status"] = "applying".into();
    fs::write(&journal_path, serde_json::to_vec(&journal).unwrap()).unwrap();
    fs::write(dir.path().join("a.ts"), "unrelated").unwrap();
    assert_eq!(
        engine.recover(&preview.id).unwrap_err().code,
        "version_conflict"
    );
    assert_eq!(engine.pending().unwrap(), vec![preview.id.clone()]);
    assert_eq!(
        engine
            .preview(ChangeSet {
                changes: vec![Change::Create {
                    path: "b.ts".into(),
                    content: "".into()
                }]
            })
            .unwrap_err()
            .code,
        "recovery_required"
    );
    fs::write(dir.path().join("a.ts"), "new").unwrap();
    let restarted = Engine::open(dir.path()).unwrap();
    assert_eq!(restarted.recover(&preview.id).unwrap().status, "reverted");
    assert_eq!(fs::read_to_string(dir.path().join("a.ts")).unwrap(), "old");
    assert!(restarted.pending().unwrap().is_empty());
}
#[test]
fn cache_corruption_recomputes_and_reads_are_bounded() {
    let (dir, engine) = fixture();
    fs::write(dir.path().join("a.txt"), "line\n".repeat(800)).unwrap();
    let first = engine.read("a.txt", 1, 100).unwrap();
    assert!(first.truncated);
    assert_eq!(first.total_lines, 800);
    for file in fs::read_dir(dir.path().join(".shark/cache")).unwrap() {
        fs::write(file.unwrap().path(), "not json").unwrap();
    }
    assert!(!engine.read("a.txt", 1, 100).unwrap().cache_hit);
    assert!(engine.read("a.txt", 0, 20).is_err());
    fs::write(dir.path().join(".gitignore"), "ignored.txt\n").unwrap();
    fs::write(dir.path().join("ignored.txt"), "secret").unwrap();
    fs::write(dir.path().join("binary"), [0, 1, 2]).unwrap();
    assert!(
        !engine
            .list()
            .unwrap()
            .iter()
            .any(|e| e.path.contains(".shark") || e.path == "ignored.txt")
    );
    assert!(engine.search("line", 3).unwrap().truncated);
    assert!(engine.search("(", 3).is_err());
}
#[test]
fn ast_outlines_report_calls_and_imports_without_claiming_semantics() {
    let (dir, engine) = fixture();
    fs::write(dir.path().join("a.ts"), "import { other } from './b';\nexport class A { run() { other(); } }\nconst arrow = () => other();\n").unwrap();
    let outline = engine.outline("a.ts").unwrap();
    assert!(!outline.syntax_errors);
    assert_eq!(outline.imports[0].source, "./b");
    let method = outline
        .symbols
        .iter()
        .find(|s| s.qualified_name == "A::run")
        .unwrap();
    assert_eq!(method.calls[0].expression, "other");
    assert_eq!(method.calls[0].resolution, "unresolved_syntax");
    assert!(outline.symbols.iter().any(|s| s.name == "arrow"));
    fs::write(
        dir.path().join("lib.rs"),
        "use std::fs;\nstruct Engine;\nimpl Engine { fn run() { work(); } }\n",
    )
    .unwrap();
    let rust = engine.outline("lib.rs").unwrap();
    assert!(
        rust.symbols
            .iter()
            .any(|s| s.qualified_name == "Engine::run")
    );
    assert!(engine.outline("a.txt").is_err());
}
#[test]
fn json_protocol_returns_structured_errors_and_paged_inventory() {
    let (dir, engine) = fixture();
    for n in 0..4 {
        fs::write(dir.path().join(format!("{n}.txt")), "a").unwrap();
    }
    let result = engine.dispatch(r#"{"id":1,"method":"workspace/list","params":{"limit":2}}"#);
    assert_eq!(result["result"]["total"], 4);
    assert_eq!(result["result"]["next_offset"], 2);
    assert_eq!(
        engine.dispatch(
            r#"{"id":2,"method":"file/read","params":{"path":"0.txt","unexpected":true}}"#
        )["error"]["code"],
        "invalid_params"
    );
    assert_eq!(
        engine.dispatch(r#"{"id":3,"method":"nope"}"#)["error"]["code"],
        "unknown_method"
    );
    assert_eq!(
        engine.dispatch("invalid")["error"]["code"],
        "invalid_request"
    );
}
#[cfg(unix)]
#[test]
fn symlinks_are_rejected_and_executable_mode_survives_changes() {
    use std::os::unix::fs::{PermissionsExt, symlink};
    let (dir, engine) = fixture();
    symlink("/etc/passwd", dir.path().join("escape")).unwrap();
    assert_eq!(
        engine.read("escape", 1, 20).unwrap_err().code,
        "symlink_path"
    );
    fs::write(dir.path().join("run.sh"), "echo old\n").unwrap();
    fs::set_permissions(dir.path().join("run.sh"), fs::Permissions::from_mode(0o755)).unwrap();
    let p = engine
        .preview(ChangeSet {
            changes: vec![edit("run.sh", "old", "new", &digest("echo old\n"))],
        })
        .unwrap();
    engine.apply(&p.id).unwrap();
    assert_eq!(
        fs::metadata(dir.path().join("run.sh"))
            .unwrap()
            .permissions()
            .mode()
            & 0o777,
        0o755
    );
    engine.revert(&p.id).unwrap();
    assert_eq!(
        fs::metadata(dir.path().join("run.sh"))
            .unwrap()
            .permissions()
            .mode()
            & 0o777,
        0o755
    );
}
#[test]
fn overlapping_matches_are_not_mistaken_for_a_unique_replacement() {
    let (dir, engine) = fixture();
    fs::write(dir.path().join("a.txt"), "aaa").unwrap();
    assert_eq!(
        engine
            .preview(ChangeSet {
                changes: vec![edit("a.txt", "aa", "b", &digest("aaa"))]
            })
            .unwrap_err()
            .code,
        "ambiguous_edit"
    );
}
#[test]
fn deletion_and_utf8_insertions_are_reversible() {
    let (dir, engine) = fixture();
    fs::write(dir.path().join("a.txt"), "é\n").unwrap();
    let deletion = engine
        .preview(ChangeSet {
            changes: vec![Change::Delete {
                path: "a.txt".into(),
                expected_version: digest("é\n"),
            }],
        })
        .unwrap();
    engine.apply(&deletion.id).unwrap();
    assert!(!dir.path().join("a.txt").exists());
    engine.revert(&deletion.id).unwrap();
    let insertion = engine
        .preview(ChangeSet {
            changes: vec![Change::Edit {
                path: "a.txt".into(),
                expected_version: digest("é\n"),
                edits: vec![Edit::Range {
                    start_byte: 2,
                    end_byte: 2,
                    old: "".into(),
                    new: "!".into(),
                }],
            }],
        })
        .unwrap();
    engine.apply(&insertion.id).unwrap();
    assert_eq!(
        fs::read_to_string(dir.path().join("a.txt")).unwrap(),
        "é!\n"
    );
}
#[test]
fn cooperating_process_lock_blocks_mutations() {
    use fs2::FileExt;
    let (dir, engine) = fixture();
    let lock = fs::OpenOptions::new()
        .read(true)
        .write(true)
        .create(true)
        .truncate(false)
        .open(dir.path().join(".shark/workspace.lock"))
        .unwrap();
    lock.try_lock_exclusive().unwrap();
    assert_eq!(
        engine
            .preview(ChangeSet {
                changes: vec![Change::Create {
                    path: "a.txt".into(),
                    content: "x".into()
                }]
            })
            .unwrap_err()
            .code,
        "workspace_busy"
    );
    drop(lock);
    assert!(
        engine
            .preview(ChangeSet {
                changes: vec![Change::Create {
                    path: "a.txt".into(),
                    content: "x".into()
                }]
            })
            .is_ok()
    );
}
#[test]
fn read_ranges_preserve_crlf_and_unterminated_final_line() {
    let (dir, engine) = fixture();
    let source = "const first = 1;\r\nconst last = 2;";
    fs::write(dir.path().join("a.ts"), source).unwrap();
    let read = engine.read("a.ts", 1, 20).unwrap();
    assert_eq!(read.content, source);
    assert_eq!(
        engine.read("a.ts", 2, 1).unwrap().content,
        "const last = 2;"
    );
    assert_eq!(
        engine
            .artifact_read(&read.artifact_id, 1, 20)
            .unwrap()
            .content,
        source
    );
}
#[test]
fn independent_agents_can_read_and_populate_the_same_cache_concurrently() {
    let (dir, engine) = fixture();
    fs::write(dir.path().join("a.ts"), "export function read() {}\n").unwrap();
    let engine = std::sync::Arc::new(engine);
    let threads: Vec<_> = (0..8)
        .map(|_| {
            let engine = engine.clone();
            std::thread::spawn(move || {
                let outline = engine.outline("a.ts").unwrap();
                assert_eq!(outline.symbols[0].name, "read");
                let read = engine.read("a.ts", 1, 20).unwrap();
                assert_eq!(read.version, outline.version);
            })
        })
        .collect();
    for thread in threads {
        thread.join().unwrap();
    }
    assert!(engine.outline("a.ts").unwrap().cache_hit);
}
#[test]
fn oversized_outlines_are_explicitly_bounded() {
    let (dir, engine) = fixture();
    let source: String = (0..300)
        .map(|n| format!("export function function_{n}() {{ call_one(); call_two(); }}\n"))
        .collect();
    fs::write(dir.path().join("a.ts"), source).unwrap();
    let outline = engine.outline("a.ts").unwrap();
    assert!(outline.truncated);
    assert!(serde_json::to_vec(&outline).unwrap().len() <= 24000);
}
