import torch
from transformers import AutoModelForQuestionAnswering, AutoTokenizer
from pathlib import Path
import fitz
import numpy as np
from dataclasses import dataclass
from typing import Dict, List, Tuple
import logging
import json
import time
import psutil
from sklearn.model_selection import KFold
from json import JSONEncoder
import pathway as pw
from pathway.xpacks.llm.vector_store import VectorStoreServer, VectorStoreClient
from transformers import AutoTokenizer, AutoModel


@dataclass
class Paper:
    content: str
    path: Path
    is_reference: bool
    label: str = None
    conference: str = None

@dataclass
class PerformanceMetrics:
    processing_time: float
    memory_used_mb: float
    gpu_memory_mb: float = 0

class PaperClassifier:
    def __init__(self):
        self.device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
        self.conferences = ["TMLR", "CVPR", "EMNLP", "NeurIPS", "KDD"]
        self.reference_papers = []
        self._setup_models()
        self.performance_metrics = []
        self._setup_vector_store()

    def _setup_models(self):
        # Only keep RoBERTa for rationale generation
        self.qa_model = AutoModelForQuestionAnswering.from_pretrained("deepset/roberta-base-squad2").to(self.device)
        self.qa_tokenizer = AutoTokenizer.from_pretrained("deepset/roberta-base-squad2")

    def _setup_vector_store(self):
        """Initialize Pathway vector store server and client"""
        # Setup SciBERT embedder
        self.tokenizer = AutoTokenizer.from_pretrained("allenai/scibert_scivocab_uncased")
        self.scibert = AutoModel.from_pretrained("allenai/scibert_scivocab_uncased").to(self.device)
        
        def embed_text(text: str) -> list[float]:
            inputs = self.tokenizer(
                text,
                max_length=512,
                truncation=True,
                padding=True,
                return_tensors="pt"
            ).to(self.device)
            
            with torch.no_grad():
                outputs = self.scibert(**inputs)
            # Convert mean pooled output to list of floats
            embedding = outputs.last_hidden_state.mean(dim=1).cpu().numpy()[0].tolist()
            return embedding

        # Initialize server
        self.vector_server = VectorStoreServer(
            embedder=embed_text,
            parser=None  # We're handling parsing separately
        )
        
        # Start server in a thread
        self.vector_server.run_server(
            host="localhost",
            port=8000,
            threaded=True
        )
        
        # Initialize client
        self.vector_client = VectorStoreClient(
            host="localhost",
            port=8000
        )

    def _index_reference_papers(self, reference_papers: List[Paper]):
        """Index reference papers using vector store server"""
        # Create a Pathway table from reference papers
        documents = [{
            "content": paper.content,
            "metadata": {
                "label": paper.label,
                "conference": paper.conference,
                "path": str(paper.path)
            }
        } for paper in reference_papers]
        
        # The documents will be automatically indexed by the server
        table = pw.Table.from_list(documents)
        self.vector_server.add_documents(table)

    def _get_similar_papers(self, query_paper: Paper, top_k: int = 5) -> List[Dict]:
        """Query similar papers using vector store client"""
        results = self.vector_client.query(
            query=query_paper.content,
            k=top_k
        )
        return results

    def _track_performance(func):
        def wrapper(self, *args, **kwargs):
            start_time = time.time()
            torch.cuda.reset_peak_memory_stats()

            result = func(self, *args, **kwargs)

            processing_time = time.time() - start_time
            memory_used = psutil.Process().memory_info().rss / 1024 / 1024  # MB
            gpu_memory = torch.cuda.max_memory_allocated() / 1024 / 1024 if torch.cuda.is_available() else 0

            self.performance_metrics.append(PerformanceMetrics(
                processing_time=processing_time,
                memory_used_mb=memory_used,
                gpu_memory_mb=gpu_memory
            ))

            return result
        return wrapper

    def _generate_rationale(self, paper_content: str, conference: str) -> str:
        conference_contexts = {
            "TMLR": "TMLR is a machine learning research conference focusing on theoretical advances, algorithms, and methodological innovations in machine learning.",
            "CVPR": "CVPR is a premier computer vision conference focusing on visual processing, recognition, understanding, and generation.",
            "EMNLP": "EMNLP is a natural language processing conference focusing on computational linguistics, language understanding, and text processing.",
            "NeurIPS": "NeurIPS is a conference focusing on neural information processing systems, machine learning theory, and artificial intelligence.",
            "KDD": "KDD is a conference focusing on data mining, knowledge discovery, and large-scale data analytics."
        }

        content_preview = paper_content[:1000].replace('\n', ' ').strip()
        try:
            title = content_preview.split('.')[0]
            abstract = ' '.join(content_preview.split('.')[1:3])
        except:
            title = content_preview[:100]
            abstract = content_preview[100:500]

        context = (
            f"Paper Title: {title}\n"
            f"Abstract: {abstract}\n\n"
            f"Conference Information: {conference_contexts[conference]}\n\n"
            "A paper is relevant to a conference if its technical contributions and research focus align with the conference's main themes. "
            "The explanation should describe specific technical aspects of the paper that match the conference's focus areas."
        )

        questions = [
            f"What specific technical contributions make this paper relevant to {conference}?",
            f"How does this paper's methodology align with {conference}'s main themes?",
            f"What is the main innovation of this paper that fits {conference}'s focus?"
        ]

        answers = []
        for question in questions:
            inputs = self.qa_tokenizer(
                question,
                context,
                max_length=386,
                truncation=True,
                padding='max_length',
                return_tensors="pt"
            ).to(self.device)

            with torch.no_grad():
                outputs = self.qa_model(**inputs)
                start_logits = outputs.start_logits
                end_logits = outputs.end_logits

                start_idx = torch.argmax(start_logits)
                end_idx = torch.argmax(end_logits)

                tokens = self.qa_tokenizer.convert_ids_to_tokens(inputs["input_ids"][0])
                answer = self.qa_tokenizer.convert_tokens_to_string(tokens[start_idx:end_idx+1])

                if answer and len(answer.strip()) > 10:
                    answers.append(answer.strip())

        if answers:
            unique_answers = []
            for ans in answers:
                if not any(self._similar_strings(ans, existing) for existing in unique_answers):
                    unique_answers.append(ans)

            rationale = f"This paper is relevant to {conference} because " + ". ".join(unique_answers[:2])
            return rationale
        else:
            return f"This paper appears relevant to {conference} based on its focus on {title}"

    def _similar_strings(self, str1: str, str2: str, threshold: float = 0.7) -> bool:
        if len(str1) < 10 or len(str2) < 10:
            return False
        common = sum(1 for a, b in zip(str1.lower(), str2.lower()) if a == b)
        return common / max(len(str1), len(str2)) > threshold

    def load_dataset(self, base_path: str) -> Tuple[List[Paper], List[Paper]]:
        base_path = Path(base_path)
        reference_papers = []
        papers_to_classify = []

        ref_path = base_path / "Reference"
        pub_path = ref_path / "Publishable"

        for conf in self.conferences:
            conf_path = pub_path / conf
            for pdf_path in conf_path.glob("*.pdf"):
                content = self._extract_pdf_content(pdf_path)
                reference_papers.append(Paper(
                    content=content,
                    path=pdf_path,
                    is_reference=True,
                    label="Publishable",
                    conference=conf
                ))

        nonpub_path = ref_path / "Non-Publishable"
        for pdf_path in nonpub_path.glob("*.pdf"):
            content = self._extract_pdf_content(pdf_path)
            reference_papers.append(Paper(
                content=content,
                path=pdf_path,
                is_reference=True,
                label="NonPublishable"
            ))

        papers_path = base_path / "Papers"
        for pdf_path in papers_path.glob("*.pdf"):
            content = self._extract_pdf_content(pdf_path)
            papers_to_classify.append(Paper(
                content=content,
                path=pdf_path,
                is_reference=False
            ))

        self.reference_papers = reference_papers
        return reference_papers, papers_to_classify

    def _extract_pdf_content(self, pdf_path: Path) -> str:
        try:
            doc = fitz.open(pdf_path)
            text = ""
            for page in doc:
                text += page.get_text()
            return text.strip()
        except Exception as e:
            logging.error(f"Error extracting content from {pdf_path}: {e}")
            return ""

    
    @_track_performance
    def classify_papers(self, reference_papers: List[Paper], papers: List[Paper]) -> List[Dict]:
        results = []
        
        # Index reference papers
        self._index_reference_papers(reference_papers)

        for paper in papers:
            try:
                # Get similar papers
                similar_papers = self._get_similar_papers(paper)
                
                # Analyze similarity scores and metadata
                publishable_scores = []
                conference_scores = {conf: [] for conf in self.conferences}
                
                for result in similar_papers:
                    score = result.score
                    metadata = result.metadata
                    
                    if metadata["label"] == "Publishable":
                        publishable_scores.append(score)
                        if metadata["conference"]:
                            conference_scores[metadata["conference"]].append(score)
                
                # Determine publishability
                avg_publishable_score = np.mean(publishable_scores) if publishable_scores else 0
                is_publishable = avg_publishable_score > 0.7  # Threshold can be adjusted
                
                if is_publishable:
                    # Find best conference
                    conf_avg_scores = {
                        conf: np.mean(scores) if scores else 0 
                        for conf, scores in conference_scores.items()
                    }
                    best_conf = max(conf_avg_scores.items(), key=lambda x: x[1])[0]
                    
                    # Generate rationale
                    rationale = self._generate_rationale(paper.content, best_conf)
                    
                    results.append({
                        "paper_id": paper.path.stem,
                        "publishable": 1,
                        "conference": best_conf,
                        "rationale": rationale,
                        "confidence_scores": {
                            "publishability": avg_publishable_score,
                            "conference": conf_avg_scores[best_conf]
                        }
                    })
                else:
                    results.append({
                        "paper_id": paper.path.stem,
                        "publishable": 0,
                        "conference": "na",
                        "rationale": "na",
                        "confidence_scores": {
                            "publishability": avg_publishable_score
                        }
                    })

            except Exception as e:
                logging.error(f"Error processing {paper.path}: {e}")
                results.append({
                    "paper_id": paper.path.stem,
                    "publishable": 0,
                    "conference": "error",
                    "rationale": str(e),
                    "confidence_scores": {}
                })

        return results

    def calculate_metrics(self, validation_papers: List[Paper]) -> Dict:
        true_positives = 0
        false_positives = 0
        true_negatives = 0
        false_negatives = 0

        conference_correct = 0
        total_publishable = 0

        results = self.classify_papers(self.reference_papers, validation_papers)

        for paper, result in zip(validation_papers, results):
            is_actually_publishable = paper.label == "Publishable"
            is_predicted_publishable = result["publishable"] == 1

            if is_predicted_publishable and is_actually_publishable:
                true_positives += 1
                if paper.conference == result["conference"]:
                    conference_correct += 1
            elif is_predicted_publishable and not is_actually_publishable:
                false_positives += 1
            elif not is_predicted_publishable and not is_actually_publishable:
                true_negatives += 1
            else:
                false_negatives += 1

            if is_actually_publishable:
                total_publishable += 1

        accuracy = (true_positives + true_negatives) / len(validation_papers)

        precision = true_positives / (true_positives + false_positives) if (true_positives + false_positives) > 0 else 0
        recall = true_positives / (true_positives + false_negatives) if (true_positives + false_negatives) > 0 else 0
        f1 = 2 * (precision * recall) / (precision + recall) if (precision + recall) > 0 else 0

        conference_accuracy = conference_correct / total_publishable if total_publishable > 0 else 0

        return {
            "accuracy": accuracy,
            "precision": precision,
            "recall": recall,
            "f1_score": f1,
            "conference_accuracy": conference_accuracy,
            "metrics_detail": {
                "true_positives": true_positives,
                "false_positives": false_positives,
                "true_negatives": true_negatives,
                "false_negatives": false_negatives,
                "total_papers": len(validation_papers)
            }
        }

    def cross_validate(self, k_folds: int = 5) -> Dict:
        kf = KFold(n_splits=k_folds, shuffle=True, random_state=42)
        metrics_list = []

        reference_papers = np.array(self.reference_papers)

        for train_idx, val_idx in kf.split(reference_papers):
            train_papers = reference_papers[train_idx].tolist()
            val_papers = reference_papers[val_idx].tolist()

            self.reference_papers = train_papers
            metrics = self.calculate_metrics(val_papers)
            metrics_list.append(metrics)

        avg_metrics = {
            "accuracy": np.mean([m["accuracy"] for m in metrics_list]),
            "f1_score": np.mean([m["f1_score"] for m in metrics_list]),
            "conference_accuracy": np.mean([m["conference_accuracy"] for m in metrics_list])
        }

        return {
            "fold_metrics": metrics_list,
            "average_metrics": avg_metrics
        }

    def get_performance_summary(self) -> Dict:
        total_time = sum(m.processing_time for m in self.performance_metrics)
        avg_memory = np.mean([m.memory_used_mb for m in self.performance_metrics])
        max_memory = max(m.memory_used_mb for m in self.performance_metrics)

        if torch.cuda.is_available():
            avg_gpu = np.mean([m.gpu_memory_mb for m in self.performance_metrics])
            max_gpu = max(m.gpu_memory_mb for m in self.performance_metrics)
        else:
            avg_gpu = max_gpu = 0

        return {
            "total_processing_time": total_time,
            "average_time_per_operation": total_time / len(self.performance_metrics),
            "memory_usage": {
                "average_mb": avg_memory,
                "peak_mb": max_memory
            },
            "gpu_usage": {
                "average_mb": avg_gpu,
                "peak_mb": max_gpu
            },
            "total_operations": len(self.performance_metrics),
            "device_used": str(self.device),
            "vector_store_stats": {
                "indexed_documents": self.vector_store.get_stats().get("total_documents", 0),
                "embedding_dimensions": self.vector_store.get_stats().get("embedding_dimensions", 0)
            }
        }


    class NumpyEncoder(JSONEncoder):
        def default(self, obj):
            if isinstance(obj, np.integer):
                return int(obj)
            if isinstance(obj, np.floating):
                return float(obj)
            if isinstance(obj, np.ndarray):
                return obj.tolist()
            return super(NumpyEncoder, self).default(obj)


    def main():
        # Initialize classifier
        classifier = PaperClassifier()

        # Load datasets
        reference_papers, papers = classifier.load_dataset("/content/drive/MyDrive/KDSH_2025_Dataset")

        # Perform cross-validation
        cv_results = classifier.cross_validate(k_folds=5)

        # Classify papers
        classification_results = classifier.classify_papers(reference_papers, papers)

        # Get performance metrics
        performance_summary = classifier.get_performance_summary()

        # Prepare submission results (without confidence scores)
        submission_results = [{
            "paper_id": result["paper_id"],
            "publishable": result["publishable"],
            "conference": result["conference"],
            "rationale": result["rationale"]
        } for result in classification_results]

        # Prepare metrics results
        metrics_results = {
            "paper_metrics": [{
                "paper_id": result["paper_id"],
                "confidence_scores": result["confidence_scores"]
            } for result in classification_results],
            "cross_validation": cv_results,
            "performance": performance_summary
        }

        # Write submission results to results.json
        with open("results.json", "w") as f:
            json.dump(submission_results, f, indent=2, cls=NumpyEncoder)

        # Write metrics to metrics.json
        with open("metrics.json", "w") as f:
            json.dump(metrics_results, f, indent=2, cls=NumpyEncoder)

        # Log summary statistics
        logging.info("Classification Complete!")
        logging.info(f"Total processing time: {float(performance_summary['total_processing_time']):.2f} seconds")
        logging.info(f"Average CV Accuracy: {float(cv_results['average_metrics']['accuracy']):.3f}")
        logging.info(f"Average CV F1 Score: {float(cv_results['average_metrics']['f1_score']):.3f}")
        logging.info(f"Average Conference Accuracy: {float(cv_results['average_metrics']['conference_accuracy']):.3f}")
        logging.info(f"Total documents indexed: {performance_summary['vector_store_stats']['indexed_documents']}")


    if __name__ == "__main__":
        main()
