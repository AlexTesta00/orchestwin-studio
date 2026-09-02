"""Model-adaptation and evaluator-dataset bounded context."""

from orchestwin.training.dataset_examples import (
    DatasetArtifactSnapshot,
    DatasetEvidenceKind,
    DatasetEvidenceReference,
    DatasetExampleSourceKind,
    DatasetLanguage,
    DatasetRubric,
    DatasetUseRestriction,
    DatasetUserTwinReference,
    DatasetVersionedArtifactReference,
    EvaluatorDatasetExample,
    ExpectedUserTwinEvaluation,
    create_evaluator_dataset_example,
)
from orchestwin.training.dataset_manifests import (
    DatasetBuildManifest,
    DatasetBuildPolicy,
    DatasetManifestEntry,
    DatasetManifestReference,
    build_dataset_manifest,
)
from orchestwin.training.dataset_validation import (
    DatasetValidationCode,
    DatasetValidationIssue,
    DatasetValidationReport,
    validate_dataset_example,
)
from orchestwin.training.deduplication import (
    DatasetDeduplicationDecision,
    DatasetDeduplicationPolicy,
    DatasetDeduplicationResult,
    DatasetDuplicateKind,
    dataset_training_payload_hash,
    dataset_training_tokens,
    deduplicate_dataset_examples,
    default_dataset_deduplication_policy,
)
from orchestwin.training.filtering import (
    DatasetCandidate,
    DatasetCandidateDecision,
    DatasetCandidateDecisionStatus,
    DatasetCandidateRejectionCode,
    DatasetFilteringPolicy,
    DatasetFilteringResult,
    default_dataset_filtering_policy,
    filter_dataset_candidates,
)
from orchestwin.training.generation import (
    DatasetExampleGenerator,
    DatasetGenerationFailure,
    DatasetGenerationFailureKind,
    DatasetGenerationMetadata,
    DatasetGenerationRequest,
    DatasetGenerationResult,
    DatasetGenerationUsage,
    DeterministicDatasetExampleGenerator,
)
from orchestwin.training.persistence import (
    DatasetBuildQualityReport,
    InMemoryTrainingDatasetRepository,
    SqlAlchemyTrainingDatasetRepository,
    StoredTrainingDatasetVersion,
    TrainingDatasetQualityReportRecord,
    TrainingDatasetRepository,
    TrainingDatasetStoreResult,
    TrainingDatasetStoreStatus,
    TrainingDatasetVersionRecord,
    create_dataset_quality_report,
)
from orchestwin.training.scenarios import (
    DatasetTargetPlatform,
    ScenarioFamily,
    ScenarioGenerationPlan,
    ScenarioRiskDimension,
    create_scenario_generation_plans,
    default_scenario_families,
)
from orchestwin.training.splitting import (
    DatasetLeakageCode,
    DatasetLeakageIssue,
    DatasetSplit,
    DatasetSplitAssignment,
    DatasetSplitExclusionReason,
    DatasetSplitPolicy,
    DatasetSplitResult,
    default_dataset_split_policy,
    split_dataset_examples,
)

__all__ = [
    "DatasetArtifactSnapshot",
    "DatasetEvidenceKind",
    "DatasetEvidenceReference",
    "DatasetExampleSourceKind",
    "DatasetLanguage",
    "DatasetRubric",
    "DatasetUseRestriction",
    "DatasetUserTwinReference",
    "DatasetVersionedArtifactReference",
    "EvaluatorDatasetExample",
    "ExpectedUserTwinEvaluation",
    "create_evaluator_dataset_example",
]

__all__ += [
    "DatasetValidationCode",
    "DatasetValidationIssue",
    "DatasetValidationReport",
    "validate_dataset_example",
]

__all__ += [
    "DatasetBuildManifest",
    "DatasetBuildPolicy",
    "DatasetManifestEntry",
    "DatasetManifestReference",
    "build_dataset_manifest",
]


__all__ += [
    "DatasetExampleGenerator",
    "DatasetGenerationFailure",
    "DatasetGenerationFailureKind",
    "DatasetGenerationMetadata",
    "DatasetGenerationRequest",
    "DatasetGenerationResult",
    "DatasetGenerationUsage",
    "DeterministicDatasetExampleGenerator",
]

__all__ += [
    "DatasetTargetPlatform",
    "ScenarioFamily",
    "ScenarioGenerationPlan",
    "ScenarioRiskDimension",
    "create_scenario_generation_plans",
    "default_scenario_families",
]

__all__ += [
    "DatasetCandidate",
    "DatasetCandidateDecision",
    "DatasetCandidateDecisionStatus",
    "DatasetCandidateRejectionCode",
    "DatasetFilteringPolicy",
    "DatasetFilteringResult",
    "default_dataset_filtering_policy",
    "filter_dataset_candidates",
]

__all__ += [
    "DatasetDeduplicationDecision",
    "DatasetDeduplicationPolicy",
    "DatasetDeduplicationResult",
    "DatasetDuplicateKind",
    "dataset_training_payload_hash",
    "dataset_training_tokens",
    "deduplicate_dataset_examples",
    "default_dataset_deduplication_policy",
]

__all__ += [
    "DatasetLeakageCode",
    "DatasetLeakageIssue",
    "DatasetSplit",
    "DatasetSplitAssignment",
    "DatasetSplitExclusionReason",
    "DatasetSplitPolicy",
    "DatasetSplitResult",
    "default_dataset_split_policy",
    "split_dataset_examples",
]

__all__ += [
    "DatasetBuildQualityReport",
    "InMemoryTrainingDatasetRepository",
    "SqlAlchemyTrainingDatasetRepository",
    "StoredTrainingDatasetVersion",
    "TrainingDatasetQualityReportRecord",
    "TrainingDatasetRepository",
    "TrainingDatasetStoreResult",
    "TrainingDatasetStoreStatus",
    "TrainingDatasetVersionRecord",
    "create_dataset_quality_report",
]
