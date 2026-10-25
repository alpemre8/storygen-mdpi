# Historical input bindings

Status: **INPUT_BINDINGS_READY** for all four models and both conditions, subject
to full record-level validation when the researcher runs. A bounded read-only
validation checks full frozen definitions, all global lineage/instrument manifests,
original film files and one available archived task per combination. No real
before/after feature differences or complete-population eligibility statistics
were calculated during implementation.

Every exact file path and SHA-256 is in `src/assets/bindings.json`. This asset contains
only metadata, not screenplay content, model responses or feature-value fixtures.
File absence is frozen explicitly as null hash plus a missing reason. If any bound
file changes/disappears or an absent file appears, the real run aborts for deliberate
rebinding. No directory search or fallback occurs during execution.

## Global authorities

- taskset: `/home/alp-emre/projects/01-Storygen-area/storygen-rewrite-depot/runs/01b-taskset/taskset_v5/runtimes/fs_qwen25_7b_q4km_mc1_1_fev1_4_current_10_films_balanced_v1/taskset_runtime.json`
  SHA-256: `sha256:f0efdf862a5a1c999220a86a04676f8bb846b9b3191635e0b15a79a3fa341912`.
- rewrite_taskset: `/home/alp-emre/projects/01-Storygen-area/storygen-evaluation-depot/runs/04-evaluation/2.3/tasksets/taskset_v5/runtimes/fs_qwen25_7b_q4km_mc1_1_fev1_4_current_10_films_balanced_v1/taskset_runtime.json`
  SHA-256: `sha256:df31bd4b75648ab172b74fcc2c89c9a2b20cd8a88c1bf922597738e494e19730`.
- reference: `/home/alp-emre/projects/01-Storygen-area/storygen-feature-extraction-depot/history/legacy-common-depot/runs/01-feature_extraction/feature_sets_v1_4/fs_qwen25_7b_q4km_mc1_1_fev1_4_current_10_films_balanced_v1/feature_set_manifest.json`
  SHA-256: `sha256:3b656f6a8ce2a1c9a6df4cae3a6dd46d48dec09b3e14c673465c3bc52e625d77`.

Both task snapshots contain the same 240 task IDs, source/reference intervals,
bases and selected features. Historical path metadata, task difficulty fields and
feature signature aliases differ; those fields do not redefine the population.
The canonical feature-set hash is verified against both rewrite and reanalysis
manifests, and rewrite-time task hashes are verified separately.

Canonical measurement: feature-measurement-v1 / 1.1.0, Qwen2.5-7B-Instruct Q4_K_M.

Checkpoint: `sha256:65b8fcd92af6b4fefa935c625d1ac27ea29dcb6ee14589c55a8f115ceaaa1423`.

Protocol: `sha256:3c0297d30951838b583ae1ef5cf6795077191f3bc3280c4494e132d6fc9a6e6b`.

Instrument: `sha256:76bd38bd47db4edc5ff54cb7fc2a78baf1f540520d5d91869f4abfe1eeb83363`.

Prompt: `sha256:aede8ce373024f79dbea090cf5d7dbae07edd3b8f7850c683c5affd6c3ad9d24`.

Schema: `sha256:ef9ad464d0840cab9c030eb38728b0543115595dcc061a9d2069b4f7cc0a988c`.

Request: `sha256:925c856701150e0e44f2b8db13604fef047c3853c1f82cb831477f851cc82a94`.

Decoding: `sha256:3fb0b1e20561a05c7cff542021475bbe9491761eb361dbb156df39f95cc93de7`.

The complete measurement model/configuration/normalization/failure-policy payload
is frozen in the binding asset and compared for equality. Mistral E01 is excluded.
No model file or model server is read/loaded or contacted by this experiment.

## Original film measurements

- apocalypse_now: `/home/alp-emre/projects/01-Storygen-area/storygen-feature-extraction-depot/history/legacy-common-depot/runs/01-feature_extraction/feature_sets_v1_4/fs_qwen25_7b_q4km_mc1_1_fev1_4_current_10_films_balanced_v1/films/apocalypse_now/scene_features_llm.json`
  SHA-256 `sha256:9c6bf30bf3da79f1ea65e1a9607fa43a43fbd30ce7ba4c82885fc11e52f357c3`; film attestation `/home/alp-emre/projects/01-Storygen-area/storygen-feature-extraction-depot/history/legacy-common-depot/runs/01-feature_extraction/feature_sets_v1_4/fs_qwen25_7b_q4km_mc1_1_fev1_4_current_10_films_balanced_v1/films/apocalypse_now/measurement_manifest.json`
  SHA-256 `sha256:5457da438d07fba07511b41dad20756a8d8ec1bd1bb81864fd9d4cb103a3a06e`.
- chasing_amy: `/home/alp-emre/projects/01-Storygen-area/storygen-feature-extraction-depot/history/legacy-common-depot/runs/01-feature_extraction/feature_sets_v1_4/fs_qwen25_7b_q4km_mc1_1_fev1_4_current_10_films_balanced_v1/films/chasing_amy/scene_features_llm.json`
  SHA-256 `sha256:8b5be2d43cdd02dc251af64d7057fcad8ceb98661b236fdcfee1ad1fb008559e`; film attestation `/home/alp-emre/projects/01-Storygen-area/storygen-feature-extraction-depot/history/legacy-common-depot/runs/01-feature_extraction/feature_sets_v1_4/fs_qwen25_7b_q4km_mc1_1_fev1_4_current_10_films_balanced_v1/films/chasing_amy/measurement_manifest.json`
  SHA-256 `sha256:ffcf849977ffeef72062286c97ba770e62ccba05e41b5ab6075d60b445d7a4c1`.
- darkman: `/home/alp-emre/projects/01-Storygen-area/storygen-feature-extraction-depot/history/legacy-common-depot/runs/01-feature_extraction/feature_sets_v1_4/fs_qwen25_7b_q4km_mc1_1_fev1_4_current_10_films_balanced_v1/films/darkman/scene_features_llm.json`
  SHA-256 `sha256:c6869ef4bde36bd6a4090d9d6ad4a467551da4a4ec8747d1f7438def40c7244b`; film attestation `/home/alp-emre/projects/01-Storygen-area/storygen-feature-extraction-depot/history/legacy-common-depot/runs/01-feature_extraction/feature_sets_v1_4/fs_qwen25_7b_q4km_mc1_1_fev1_4_current_10_films_balanced_v1/films/darkman/measurement_manifest.json`
  SHA-256 `sha256:83b2edac7615bcaf7911c42bfba67859bd748742116936093761dfa40e99907a`.
- do_the_right_thing: `/home/alp-emre/projects/01-Storygen-area/storygen-feature-extraction-depot/history/legacy-common-depot/runs/01-feature_extraction/feature_sets_v1_4/fs_qwen25_7b_q4km_mc1_1_fev1_4_current_10_films_balanced_v1/films/do_the_right_thing/scene_features_llm.json`
  SHA-256 `sha256:b07d35d89f724839a8a6f9702c090a32e54c5448f5c35902381bd220f03c02a1`; film attestation `/home/alp-emre/projects/01-Storygen-area/storygen-feature-extraction-depot/history/legacy-common-depot/runs/01-feature_extraction/feature_sets_v1_4/fs_qwen25_7b_q4km_mc1_1_fev1_4_current_10_films_balanced_v1/films/do_the_right_thing/measurement_manifest.json`
  SHA-256 `sha256:1c6004cd4cc267a6d87354912c297797dc0da25d7a44d809a911ce41300e07ae`.
- dog_day_afternoon: `/home/alp-emre/projects/01-Storygen-area/storygen-feature-extraction-depot/history/legacy-common-depot/runs/01-feature_extraction/feature_sets_v1_4/fs_qwen25_7b_q4km_mc1_1_fev1_4_current_10_films_balanced_v1/films/dog_day_afternoon/scene_features_llm.json`
  SHA-256 `sha256:a9500ce4ab21fa78c1f7a03fdda79f22fbfd4bbd186f8b9c87952f9bcefe243e`; film attestation `/home/alp-emre/projects/01-Storygen-area/storygen-feature-extraction-depot/history/legacy-common-depot/runs/01-feature_extraction/feature_sets_v1_4/fs_qwen25_7b_q4km_mc1_1_fev1_4_current_10_films_balanced_v1/films/dog_day_afternoon/measurement_manifest.json`
  SHA-256 `sha256:91d15849cb864852eb7c1c91863c08999b0efe3666c8b757be1926f6d5762a8f`.
- drag_me_to_hell: `/home/alp-emre/projects/01-Storygen-area/storygen-feature-extraction-depot/history/legacy-common-depot/runs/01-feature_extraction/feature_sets_v1_4/fs_qwen25_7b_q4km_mc1_1_fev1_4_current_10_films_balanced_v1/films/drag_me_to_hell/scene_features_llm.json`
  SHA-256 `sha256:37d0ecf2cc8707c7677d5d7e16184079228aff70b5bbd14ac148c946e6bf191c`; film attestation `/home/alp-emre/projects/01-Storygen-area/storygen-feature-extraction-depot/history/legacy-common-depot/runs/01-feature_extraction/feature_sets_v1_4/fs_qwen25_7b_q4km_mc1_1_fev1_4_current_10_films_balanced_v1/films/drag_me_to_hell/measurement_manifest.json`
  SHA-256 `sha256:64fb56b3ccf6ea85a656f6172cc558ffc24eae2775416c5bc7d3a3963eef9912`.
- ghostbusters_ii: `/home/alp-emre/projects/01-Storygen-area/storygen-feature-extraction-depot/history/legacy-common-depot/runs/01-feature_extraction/feature_sets_v1_4/fs_qwen25_7b_q4km_mc1_1_fev1_4_current_10_films_balanced_v1/films/ghostbusters_ii/scene_features_llm.json`
  SHA-256 `sha256:be22bf5df81479be9117404fc4731bc5db841a80a17478d6a0e8c211283e8c5a`; film attestation `/home/alp-emre/projects/01-Storygen-area/storygen-feature-extraction-depot/history/legacy-common-depot/runs/01-feature_extraction/feature_sets_v1_4/fs_qwen25_7b_q4km_mc1_1_fev1_4_current_10_films_balanced_v1/films/ghostbusters_ii/measurement_manifest.json`
  SHA-256 `sha256:bce9a252daa88b5431f37dc700f71635666888c8ac4baad32710a92b5ec29ad2`.
- the_private_life_of_sherlock_holmes: `/home/alp-emre/projects/01-Storygen-area/storygen-feature-extraction-depot/history/legacy-common-depot/runs/01-feature_extraction/feature_sets_v1_4/fs_qwen25_7b_q4km_mc1_1_fev1_4_current_10_films_balanced_v1/films/the_private_life_of_sherlock_holmes/scene_features_llm.json`
  SHA-256 `sha256:1570f6b0dbbb7729ef887fdf8a5255ef99465df106ef064b42e24071ad88f510`; film attestation `/home/alp-emre/projects/01-Storygen-area/storygen-feature-extraction-depot/history/legacy-common-depot/runs/01-feature_extraction/feature_sets_v1_4/fs_qwen25_7b_q4km_mc1_1_fev1_4_current_10_films_balanced_v1/films/the_private_life_of_sherlock_holmes/measurement_manifest.json`
  SHA-256 `sha256:4816092e0e637269036a715c9d5a3f6beb6a64e8284cbcba8e157550658bfbf2`.
- the_white_ribbon: `/home/alp-emre/projects/01-Storygen-area/storygen-feature-extraction-depot/history/legacy-common-depot/runs/01-feature_extraction/feature_sets_v1_4/fs_qwen25_7b_q4km_mc1_1_fev1_4_current_10_films_balanced_v1/films/the_white_ribbon/scene_features_llm.json`
  SHA-256 `sha256:78953ea31402f6127ff10f21b9d7ec7db135169ae3471dff006695e1d54dd8e8`; film attestation `/home/alp-emre/projects/01-Storygen-area/storygen-feature-extraction-depot/history/legacy-common-depot/runs/01-feature_extraction/feature_sets_v1_4/fs_qwen25_7b_q4km_mc1_1_fev1_4_current_10_films_balanced_v1/films/the_white_ribbon/measurement_manifest.json`
  SHA-256 `sha256:ad6d7b85eb7b20e3509276e6287bdeedead49b278e06c879e4110dacbda91773`.
- up_2009: `/home/alp-emre/projects/01-Storygen-area/storygen-feature-extraction-depot/history/legacy-common-depot/runs/01-feature_extraction/feature_sets_v1_4/fs_qwen25_7b_q4km_mc1_1_fev1_4_current_10_films_balanced_v1/films/up_2009/scene_features_llm.json`
  SHA-256 `sha256:d5ee69472f2c2044d0b0db9d9b4434085d11f3a67a2acb0f5ffb521788e31ed5`; film attestation `/home/alp-emre/projects/01-Storygen-area/storygen-feature-extraction-depot/history/legacy-common-depot/runs/01-feature_extraction/feature_sets_v1_4/fs_qwen25_7b_q4km_mc1_1_fev1_4_current_10_films_balanced_v1/films/up_2009/measurement_manifest.json`
  SHA-256 `sha256:1f3bb19c766ad2f65cba8054f552dc0ea967a6c17736922cd764059c7f6054c8`.

## Exact historical model-condition sources

The inventory counts below describe consolidated file availability and historical
manifest completion, **not newly validated complete measurements**. Expected tasks
remain 240 for every row. Scientific complete/partial/invalid coverage is calculated
only during the researcher's full run.

| Model | Condition | Rewrite files | Reanalysis files | Historical missing tasks |
|---|---|---:|---:|---:|
| qwen25_7b | DP-v1 | 239 | 239 | 1 |
| qwen25_7b | CG-v1 | 235 | 235 | 5 |
| llama31_8b | DP-v1 | 237 | 237 | 3 |
| llama31_8b | CG-v1 | 234 | 234 | 6 |
| qwen35_9b | DP-v1 | 224 | 224 | 16 |
| qwen35_9b | CG-v1 | 206 | 206 | 34 |
| gemma3_12b | DP-v1 | 239 | 239 | 1 |
| gemma3_12b | CG-v1 | 238 | 238 | 2 |

### qwen25_7b DP-v1

Rewrite manifest: `/home/alp-emre/projects/01-Storygen-area/storygen-rewrite-depot/runs/02-rewrite/1.3/full240_singlepass_fresh_dp_cg_mc1_1_fev1_4_ctx12288_v1/tasksetv5_mc1_1_fev1_4_rwv1_3_qwen25_7b_q4km_full240_singlepass_c8_ctx12288_dp_v1_v1/rewrite_run_manifest.json`

Hash: `sha256:0e2a75a3a1be09ceac36e5658ace19e333776362bceb2ab4ad2a0c867790bcfb`.

Qwen reanalysis manifest: `/home/alp-emre/projects/01-Storygen-area/storygen-feature-extraction-depot/history/legacy-common-depot/runs/03-reanalysis/1.1/full240_singlepass_fresh_dp_cg_mc1_1_fev1_4_ctx12288_v1/tasksetv5_mc1_1_fev1_4_rwv1_3_qwen25_7b_q4km_full240_singlepass_c8_ctx12288_dp_v1_v1__rean_mc1_1_rav1_1_qwen25_c8_ctx12288_v1/reanalysis_manifest.json`

Hash: `sha256:c71c5f0da0335b3fd228a8b61e892720465d4159a4a169ac2123f394e1860ef2`.

Expected historical missing task outputs: `v5_T0229`.
Missing roles per listed task: consolidated rewrite, rewrite phase status, rewritten scene features, measurement status. Exact locators are listed with null hash in the binding asset. Task definitions and transfer plans remain available for every task. Historical manifest failure stages/types are retained separately.

### qwen25_7b CG-v1

Rewrite manifest: `/home/alp-emre/projects/01-Storygen-area/storygen-rewrite-depot/runs/02-rewrite/1.3/full240_singlepass_fresh_dp_cg_mc1_1_fev1_4_ctx12288_v1/tasksetv5_mc1_1_fev1_4_rwv1_3_qwen25_7b_q4km_full240_singlepass_c8_ctx12288_cg_v1_v1/rewrite_run_manifest.json`

Hash: `sha256:1a3f67545e706b85c37bfe07bb5438f361df0ba8f4893dbccf96f0ee45c8c343`.

Qwen reanalysis manifest: `/home/alp-emre/projects/01-Storygen-area/storygen-feature-extraction-depot/history/legacy-common-depot/runs/03-reanalysis/1.1/full240_singlepass_fresh_dp_cg_mc1_1_fev1_4_ctx12288_v1/tasksetv5_mc1_1_fev1_4_rwv1_3_qwen25_7b_q4km_full240_singlepass_c8_ctx12288_cg_v1_v1__rean_mc1_1_rav1_1_qwen25_c8_ctx12288_v1/reanalysis_manifest.json`

Hash: `sha256:afb4216d9eda93f3d1f624a6d9e9510df7834ca588b9d968e3a2c235062b06e8`.

Expected historical missing task outputs: `v5_T0004`, `v5_T0008`, `v5_T0139`, `v5_T0203`, `v5_T0233`.
Missing roles per listed task: consolidated rewrite, rewrite phase status, rewritten scene features, measurement status. Exact locators are listed with null hash in the binding asset. Task definitions and transfer plans remain available for every task. Historical manifest failure stages/types are retained separately.

### llama31_8b DP-v1

Rewrite manifest: `/home/alp-emre/projects/01-Storygen-area/storygen-rewrite-depot/runs/02-rewrite/1.3/full240_singlepass_fresh_dp_cg_mc1_1_fev1_4_ctx12288_v1/tasksetv5_mc1_1_fev1_4_rwv1_3_llama31_8b_q4km_full240_singlepass_c4_ctx12288_dp_v1_v1/rewrite_run_manifest.json`

Hash: `sha256:961600225fff83ed6e52bf6cb58004a27bb7812fadb78d26464a475228a5d5a1`.

Qwen reanalysis manifest: `/home/alp-emre/projects/01-Storygen-area/storygen-feature-extraction-depot/history/legacy-common-depot/runs/03-reanalysis/1.1/full240_singlepass_fresh_dp_cg_mc1_1_fev1_4_ctx12288_v1/tasksetv5_mc1_1_fev1_4_rwv1_3_llama31_8b_q4km_full240_singlepass_c4_ctx12288_dp_v1_v1__rean_mc1_1_rav1_1_qwen25_c8_ctx12288_v1/reanalysis_manifest.json`

Hash: `sha256:e871006d8390f17fe782a6bd953fee007a9c40f113bde8458568a684d2ec78f5`.

Expected historical missing task outputs: `v5_T0178`, `v5_T0187`, `v5_T0219`.
Missing roles per listed task: consolidated rewrite, rewrite phase status, rewritten scene features, measurement status. Exact locators are listed with null hash in the binding asset. Task definitions and transfer plans remain available for every task. Historical manifest failure stages/types are retained separately.

### llama31_8b CG-v1

Rewrite manifest: `/home/alp-emre/projects/01-Storygen-area/storygen-rewrite-depot/runs/02-rewrite/1.3/full240_singlepass_fresh_dp_cg_mc1_1_fev1_4_ctx12288_v1/tasksetv5_mc1_1_fev1_4_rwv1_3_llama31_8b_q4km_full240_singlepass_c4_ctx12288_cg_v1_v1/rewrite_run_manifest.json`

Hash: `sha256:a2712501ebff25fd8f106f6ac9adab52e6d135e235c216b1b986137716546c2e`.

Qwen reanalysis manifest: `/home/alp-emre/projects/01-Storygen-area/storygen-feature-extraction-depot/history/legacy-common-depot/runs/03-reanalysis/1.1/full240_singlepass_fresh_dp_cg_mc1_1_fev1_4_ctx12288_v1/tasksetv5_mc1_1_fev1_4_rwv1_3_llama31_8b_q4km_full240_singlepass_c4_ctx12288_cg_v1_v1__rean_mc1_1_rav1_1_qwen25_c8_ctx12288_v1/reanalysis_manifest.json`

Hash: `sha256:99bd48363387e71d305af3706cac8590868152d17120c9f764f621d6515b0740`.

Expected historical missing task outputs: `v5_T0108`, `v5_T0174`, `v5_T0175`, `v5_T0183`, `v5_T0206`, `v5_T0219`.
Missing roles per listed task: consolidated rewrite, rewrite phase status, rewritten scene features, measurement status. Exact locators are listed with null hash in the binding asset. Task definitions and transfer plans remain available for every task. Historical manifest failure stages/types are retained separately.

### qwen35_9b DP-v1

Rewrite manifest: `/home/alp-emre/projects/01-Storygen-area/storygen-rewrite-depot/runs/02-rewrite/1.3/full240_singlepass_fresh_dp_cg_mc1_1_fev1_4_ctx12288_v1/tasksetv5_mc1_1_fev1_4_rwv1_3_qwen35_9b_q4km_full240_singlepass_c4_ctx12288_dp_v1_v1/rewrite_run_manifest.json`

Hash: `sha256:ad56019edb963792dc0470eda6b2fa986a80390ec0c37143fd462fe82a6cf673`.

Qwen reanalysis manifest: `/home/alp-emre/projects/01-Storygen-area/storygen-feature-extraction-depot/history/legacy-common-depot/runs/03-reanalysis/1.1/full240_singlepass_fresh_dp_cg_mc1_1_fev1_4_ctx12288_v1/tasksetv5_mc1_1_fev1_4_rwv1_3_qwen35_9b_q4km_full240_singlepass_c4_ctx12288_dp_v1_v1__rean_mc1_1_rav1_1_qwen25_c8_ctx12288_v1/reanalysis_manifest.json`

Hash: `sha256:1aeca4fc3dccffb3929d5448143ce66c9790dc11f76108044c6502727195514e`.

Expected historical missing task outputs: `v5_T0003`, `v5_T0018`, `v5_T0019`, `v5_T0028`, `v5_T0033`, `v5_T0053`, `v5_T0058`, `v5_T0103`, `v5_T0108`, `v5_T0123`, `v5_T0148`, `v5_T0168`, `v5_T0183`, `v5_T0193`, `v5_T0218`, `v5_T0238`.
Missing roles per listed task: consolidated rewrite, rewrite phase status, rewritten scene features, measurement status. Exact locators are listed with null hash in the binding asset. Task definitions and transfer plans remain available for every task. Historical manifest failure stages/types are retained separately.

### qwen35_9b CG-v1

Rewrite manifest: `/home/alp-emre/projects/01-Storygen-area/storygen-rewrite-depot/runs/02-rewrite/1.3/full240_singlepass_fresh_dp_cg_mc1_1_fev1_4_ctx12288_v1/tasksetv5_mc1_1_fev1_4_rwv1_3_qwen35_9b_q4km_full240_singlepass_c4_ctx12288_cg_v1_v1/rewrite_run_manifest.json`

Hash: `sha256:8400890f7bd2f12ca152a627172ea50239d9d78586a98873bcb18d5b2c0826c8`.

Qwen reanalysis manifest: `/home/alp-emre/projects/01-Storygen-area/storygen-feature-extraction-depot/history/legacy-common-depot/runs/03-reanalysis/1.1/full240_singlepass_fresh_dp_cg_mc1_1_fev1_4_ctx12288_v1/tasksetv5_mc1_1_fev1_4_rwv1_3_qwen35_9b_q4km_full240_singlepass_c4_ctx12288_cg_v1_v1__rean_mc1_1_rav1_1_qwen25_c8_ctx12288_v1/reanalysis_manifest.json`

Hash: `sha256:da0ed88ffcd1aec8b52d0def7eda5c38fb35154bbf8352d2e116a43d9a89d8ac`.

Expected historical missing task outputs: `v5_T0001`, `v5_T0008`, `v5_T0023`, `v5_T0028`, `v5_T0033`, `v5_T0038`, `v5_T0039`, `v5_T0058`, `v5_T0068`, `v5_T0083`, `v5_T0088`, `v5_T0096`, `v5_T0099`, `v5_T0103`, `v5_T0108`, `v5_T0109`, `v5_T0110`, `v5_T0118`, `v5_T0133`, `v5_T0136`, `v5_T0138`, `v5_T0143`, `v5_T0148`, `v5_T0168`, `v5_T0173`, `v5_T0176`, `v5_T0178`, `v5_T0195`, `v5_T0203`, `v5_T0210`, `v5_T0218`, `v5_T0223`, `v5_T0228`, `v5_T0230`.
Missing roles per listed task: consolidated rewrite, rewrite phase status, rewritten scene features, measurement status. Exact locators are listed with null hash in the binding asset. Task definitions and transfer plans remain available for every task. Historical manifest failure stages/types are retained separately.

### gemma3_12b DP-v1

Rewrite manifest: `/home/alp-emre/projects/01-Storygen-area/storygen-rewrite-depot/runs/02-rewrite/1.3/full240_singlepass_fresh_dp_cg_mc1_1_fev1_4_ctx12288_v1/tasksetv5_mc1_1_fev1_4_rwv1_3_gemma3_12b_q4km_full240_singlepass_c4_ctx12288_dp_v1_v1/rewrite_run_manifest.json`

Hash: `sha256:2c6b850840021d48c5703101580333a73b6ae0cc982c60f6ccb8a95bf13b8fed`.

Qwen reanalysis manifest: `/home/alp-emre/projects/01-Storygen-area/storygen-feature-extraction-depot/history/legacy-common-depot/runs/03-reanalysis/1.1/full240_singlepass_fresh_dp_cg_mc1_1_fev1_4_ctx12288_v1/tasksetv5_mc1_1_fev1_4_rwv1_3_gemma3_12b_q4km_full240_singlepass_c4_ctx12288_dp_v1_v1__rean_mc1_1_rav1_1_qwen25_c8_ctx12288_v1/reanalysis_manifest.json`

Hash: `sha256:f3b866ddb85e0434f909d146c4a795ca2ff3f1f00d12dbc6e4ea031f1ff0ef59`.

Expected historical missing task outputs: `v5_T0227`.
Missing roles per listed task: consolidated rewrite, rewrite phase status, rewritten scene features, measurement status. Exact locators are listed with null hash in the binding asset. Task definitions and transfer plans remain available for every task. Historical manifest failure stages/types are retained separately.

### gemma3_12b CG-v1

Rewrite manifest: `/home/alp-emre/projects/01-Storygen-area/storygen-rewrite-depot/runs/02-rewrite/1.3/full240_singlepass_fresh_dp_cg_mc1_1_fev1_4_ctx12288_v1/tasksetv5_mc1_1_fev1_4_rwv1_3_gemma3_12b_q4km_full240_singlepass_c4_ctx12288_cg_v1_v1/rewrite_run_manifest.json`

Hash: `sha256:6d7756bc3b6135ef7dd97e86b348ff45103d1bf1e3c79b92efeddca0af2a81b1`.

Qwen reanalysis manifest: `/home/alp-emre/projects/01-Storygen-area/storygen-feature-extraction-depot/history/legacy-common-depot/runs/03-reanalysis/1.1/full240_singlepass_fresh_dp_cg_mc1_1_fev1_4_ctx12288_v1/tasksetv5_mc1_1_fev1_4_rwv1_3_gemma3_12b_q4km_full240_singlepass_c4_ctx12288_cg_v1_v1__rean_mc1_1_rav1_1_qwen25_c8_ctx12288_v1/reanalysis_manifest.json`

Hash: `sha256:f08ee02f07c0727491f76b9d3d834ad8030130c1f7bb1b581a4699498dcbb724`.

Expected historical missing task outputs: `v5_T0046`, `v5_T0226`.
Missing roles per listed task: consolidated rewrite, rewrite phase status, rewritten scene features, measurement status. Exact locators are listed with null hash in the binding asset. Task definitions and transfer plans remain available for every task. Historical manifest failure stages/types are retained separately.

## Provenance and boundaries

Every task binds its archived task definition, transfer plan, rewrite phase,
consolidated rewritten scenes (hash plus scene IDs only), rewritten feature values
and measurement attestation. The reanalysis attestation hashes a compact sorted
JSON map of the rewrite and transfer-plan file hashes; this exact data-identity
format is verified independently of the global manifest chain.

Historical failures remain expected missingness. Changed/missing bound files,
wrong frozen population, unsupported schema or incompatible global measurement
identity are broken experiment bindings and abort. Scene/record inconsistencies
are explicitly classified, never replaced with zero. Old E05 textual prompt
completeness/preservation rules are irrelevant to numerical measurement lineage
and are not applied. No TI/DA evaluation filters or E05 judge outputs are used.

E05-v3 documentation was used only as a discovery hint for the physical TasksetV5,
original Qwen feature set and Gemma full240 batch. The full four-model batch was
independently enumerated from the actual rewrite and reanalysis manifests; no
E05-v3 private code, eligibility selection or twenty-task restriction is imported.

Inspected source release commits (not asserted to be historical generation-time
Git checkouts; archived manifest protocol/model identities remain authoritative):

- `storygen-rewrite`: `a5be79f0c6421387e4bac27be82ad19a15b2a92a` at `/home/alp-emre/projects/01-Storygen-area/storygen-rewrite`.
- `storygen-feature-extraction`: `95b65341c678a9ec4d3d5b6710213f2097732438` at `/home/alp-emre/projects/01-Storygen-area/storygen-feature-extraction`.
- `storygen-evaluation`: `5d69c5d5b195fbc7511058ea638b799c38aed17d` at `/home/alp-emre/projects/01-Storygen-area/storygen-evaluation`.

Actual execution software/runtime versions, bootstrap rules and selection are
added to input_provenance.json at PREPARE; central run.lock.json seals the current
implementation source commit, source hashes and exact installed package closure.
There is no literal standalone storygen-measurement repository here; the canonical
instrument is historically owned by the existing feature-extraction/measurement
source trees. This experiment consumes their recorded artifacts, not a substitute.
