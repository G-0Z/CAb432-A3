data "archive_file" "lambda_zip" {
  type        = "zip"
  source_dir  = "${path.module}/../lambda"
  output_path = "${path.module}/lambda.zip"
}

resource "aws_iam_role" "lambda_role" {
  name = "queue_length_monitor_role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "lambda.amazonaws.com"
        }
      }
    ]
  })
}

resource "aws_iam_role_policy" "lambda_policy" {
  name   = "queue_length_monitor_policy"
  role   = aws_iam_role.lambda_role.id
  policy = file("${path.module}/../infra/lambda_policy.json")
}

resource "aws_lambda_function" "queue_length_monitor" {
  filename      = data.archive_file.lambda_zip.output_path
  function_name = "queue_length_monitor"
  role          = aws_iam_role.lambda_role.arn
  handler       = "queue_length_monitor.lambda_handler"
  runtime       = "python3.12"
  environment {
    variables = {
      QUEUE_URL = "https://sqs.ap-southeast-2.amazonaws.com/901444280953/image-processing-queue-n11543027"
    }
  }
  source_code_hash = data.archive_file.lambda_zip.output_base64sha256
}

resource "aws_cloudwatch_event_rule" "lambda_trigger" {
  name                = "queue_length_monitor_trigger"
  schedule_expression = "rate(1 minute)"
}

resource "aws_cloudwatch_event_target" "lambda_target" {
  rule      = aws_cloudwatch_event_rule.lambda_trigger.name
  target_id = "queue_length_monitor"
  arn       = aws_lambda_function.queue_length_monitor.arn
}

resource "aws_lambda_permission" "allow_eventbridge" {
  statement_id  = "AllowExecutionFromEventBridge"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.queue_length_monitor.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.lambda_trigger.arn
}

resource "aws_cloudwatch_metric_alarm" "queue_length_alarm" {
  alarm_name          = "high_queue_length"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "QueueLength"
  namespace           = "Custom/SQS"
  period              = 60
  statistic           = "Average"
  threshold           = 5
  alarm_actions       = [aws_autoscaling_policy.scale_out.arn]
  dimensions = {}
}

resource "aws_autoscaling_policy" "scale_out" {
  name                   = "scale_out"
  scaling_adjustment     = 1
  adjustment_type        = "ChangeInCapacity"
  cooldown               = 60
  autoscaling_group_name = "n11543027-worker-asg"  # Your ASG
}
