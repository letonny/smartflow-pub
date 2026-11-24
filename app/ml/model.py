import os
import json
import logging
import math
from typing import List, Dict, Any, Tuple

logger = logging.getLogger("smartflow.ml.model")

class TravelTimeModel:
    """
    Lightweight, pure-Python Linear Regression model for predicting road segment 
    travel times. Predicts a travel time multiplier based on congestion score, 
    precipitation, and temperature.
    
    Uses pure-Python list operations to train weights via Gradient Descent (MSE loss).
    """
    def __init__(self):
        self.weights_loaded = False
        # Default weights derived from domain knowledge
        # y_multiplier = w0 + w1 * congestion_score + w2 * rain_intensity + w3 * temp_deviation
        self.w0 = 1.0        # Baseline multiplier (free flow)
        self.w1 = 3.0        # Congestion weight (highly congested traffic takes ~4x longer)
        self.w2 = 0.05       # Rain intensity weight (e.g. 10mm/h adds 0.5 to multiplier)
        self.w3 = 0.01       # Temp deviation weight (extreme weather adds minor delays)

    def predict(
        self, 
        length_meters: float, 
        speed_limit_kmh: float, 
        congestion_score: float, 
        rain_intensity: float, 
        temperature: float
    ) -> float:
        """
        Predicts travel duration on a road segment in seconds.
        
        Formula:
          1. Free-flow time = length / speed_limit (converted to m/s)
          2. Multiplier = w0 + w1*congestion + w2*rain + w3*abs(temp - 20)
          3. Predicted time = free_flow_time * multiplier
        """
        values = (length_meters, speed_limit_kmh, congestion_score, rain_intensity, temperature)
        if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in values):
            raise ValueError("Prediction features must be finite numbers")
        if not (0 < length_meters <= 1_000_000 and 0 < speed_limit_kmh <= 300 and
                0 <= congestion_score <= 1 and 0 <= rain_intensity <= 200 and -80 <= temperature <= 80):
            raise ValueError("Prediction features are outside valid ranges")
        speed_limit_ms = speed_limit_kmh / 3.6
        free_flow_time = length_meters / speed_limit_ms
        
        # Features
        x1 = max(0.0, min(1.0, congestion_score))
        x2 = max(0.0, rain_intensity)
        x3 = abs(temperature - 20.0)
        
        # Inference
        multiplier = self.w0 + (self.w1 * x1) + (self.w2 * x2) + (self.w3 * x3)
        multiplier = max(1.0, multiplier) # Ensure travel time is at least free-flow
        
        predicted_time = free_flow_time * multiplier
        return round(predicted_time, 2)

    def fit(self, dataset: List[Dict[str, Any]], epochs: int = 500, lr: float = 0.01) -> Dict[str, Any]:
        """
        Trains model weights on historical database recordings using Gradient Descent.
        
        Each item in dataset must have:
          - "length": float (meters)
          - "speed_limit": float (km/h)
          - "congestion_score": float (0.0 to 1.0)
          - "rain_intensity": float (mm/h)
          - "temperature": float (C)
          - "actual_time": float (seconds)
        """
        if not dataset:
            logger.warning("Empty training dataset provided. Skipping model fit.")
            return {"status": "skipped", "reason": "No data"}

        logger.info(f"Initiating training session on {len(dataset)} samples for {epochs} epochs...")
        
        # Prepare feature matrices and targets in pure Python lists
        features: List[Tuple[float, float, float, float]] = []
        targets: List[float] = [] # actual multipliers
        
        if epochs <= 0 or not math.isfinite(lr) or lr <= 0:
            raise ValueError("epochs and learning rate must be positive")
        for item in dataset:
            length = item.get("length")
            speed_limit = item.get("speed_limit")
            actual_time = item.get("actual_time")
            values = (length, speed_limit, actual_time, item.get("congestion_score"), item.get("rain_intensity"), item.get("temperature"))
            if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in values):
                continue
            if not (0 < length <= 1_000_000 and 0 < speed_limit <= 300 and actual_time > 0 and
                    0 <= item["congestion_score"] <= 1 and 0 <= item["rain_intensity"] <= 200 and
                    -80 <= item["temperature"] <= 80):
                continue
            speed_limit_ms = speed_limit / 3.6
            free_flow_time = length / speed_limit_ms
            if not math.isfinite(free_flow_time) or free_flow_time <= 0:
                continue
                
            # Target actual multiplier
            actual_multiplier = actual_time / free_flow_time
            if not math.isfinite(actual_multiplier) or actual_multiplier > 100:
                continue
            
            x0 = 1.0 # Bias term
            x1 = max(0.0, min(1.0, item.get("congestion_score", 0.0)))
            x2 = max(0.0, item.get("rain_intensity", 0.0))
            x3 = abs(item.get("temperature", 20.0) - 20.0)
            
            features.append((x0, x1, x2, x3))
            targets.append(actual_multiplier)
            
        N = len(features)
        if N == 0:
            logger.warning("No valid training samples compiled. Skipping model fit.")
            return {"status": "skipped", "reason": "No valid samples"}

        # Initialize weights
        w0, w1, w2, w3 = self.w0, self.w1, self.w2, self.w3
        
        for epoch in range(epochs):
            loss = 0.0
            grad_w0 = 0.0
            grad_w1 = 0.0
            grad_w2 = 0.0
            grad_w3 = 0.0
            
            for idx in range(N):
                x0, x1, x2, x3 = features[idx]
                target_mult = targets[idx]
                
                # Predict multiplier
                pred_mult = w0*x0 + w1*x1 + w2*x2 + w3*x3
                error = pred_mult - target_mult
                
                loss += error ** 2
                
                # Gradients (derivative of MSE loss w.r.t weights)
                grad_w0 += (2.0 / N) * error * x0
                grad_w1 += (2.0 / N) * error * x1
                grad_w2 += (2.0 / N) * error * x2
                grad_w3 += (2.0 / N) * error * x3
                
            # Update weights (gradient descent)
            w0 -= lr * grad_w0
            w1 -= lr * grad_w1
            w2 -= lr * grad_w2
            w3 -= lr * grad_w3
            
            # Bound weights to prevent negative multiplier values
            w0 = max(0.5, w0)
            w1 = max(0.0, w1)
            w2 = max(0.0, w2)
            w3 = max(0.0, w3)
            if not all(math.isfinite(w) for w in (w0, w1, w2, w3)):
                raise ValueError("Training diverged; reduce learning rate or scale features")
            
            if epoch % 100 == 0 or epoch == epochs - 1:
                mse = loss / N
                logger.info(f"Epoch {epoch}/{epochs} | MSE Loss: {mse:.6f} | Weights: [{w0:.4f}, {w1:.4f}, {w2:.4f}, {w3:.4f}]")
                
        # Commit trained weights
        self.w0 = w0
        self.w1 = w1
        self.w2 = w2
        self.w3 = w3
        
        logger.info("Training completed successfully and weights updated.")
        return {
            "status": "success",
            "samples": N,
            "final_loss": loss / N,
            "weights": {"w0": w0, "w1": w1, "w2": w2, "w3": w3}
        }

    def save(self, file_path: str):
        """Saves current weights to a JSON file."""
        weights = {
            "w0": self.w0,
            "w1": self.w1,
            "w2": self.w2,
            "w3": self.w3
        }
        try:
            directory = os.path.dirname(file_path)
            if directory:
                os.makedirs(directory, exist_ok=True)
            with open(file_path, "w") as f:
                json.dump(weights, f, indent=4)
            logger.info("Saved model weights")
        except Exception as e:
            logger.error("Failed to save model weights: %s", type(e).__name__)

    def load(self, file_path: str):
        """Loads weights from a JSON file."""
        if not os.path.exists(file_path):
            logger.warning("Weights file unavailable. Keeping current defaults.")
            return
            
        try:
            with open(file_path, "r") as f:
                weights = json.load(f)
            values = [weights[key] for key in ("w0", "w1", "w2", "w3")]
            if not all(isinstance(v, (int, float)) and math.isfinite(v) and v >= 0 for v in values):
                raise ValueError("Weights must be finite nonnegative numbers")
            self.w0, self.w1, self.w2, self.w3 = values
            self.weights_loaded = True
            logger.info("Loaded model weights")
        except Exception as e:
            logger.error("Failed to load model weights (%s). Keeping current defaults.", type(e).__name__)
