============================
Database Maintenance Guide
============================

Overview
--------

ActingWeb stores temporary data (tokens, sessions, auth codes) in DynamoDB's
attribute storage. This data has defined lifetimes and should be automatically
cleaned up to prevent unbounded database growth.

This guide explains how to configure your deployment for proper data lifecycle
management.

.. note::

   ActingWeb is designed for AWS Lambda deployments where hundreds of containers
   may scale concurrently. **Never add cleanup logic to your serving path** as
   this impacts cold start time and request latency.

DynamoDB TTL Configuration
--------------------------

ActingWeb stores a ``ttl_timestamp`` field on temporary data. You must enable
DynamoDB TTL on your attributes table for automatic cleanup.

Why TTL?
~~~~~~~~

- Zero runtime overhead in your Lambda functions
- DynamoDB handles deletion automatically in the background
- No impact on cold start time or request latency
- Works reliably at any scale

Enabling TTL
~~~~~~~~~~~~

**Using AWS CLI:**

.. code-block:: bash

    aws dynamodb update-time-to-live \
      --table-name {your_prefix}_attributes \
      --time-to-live-specification "Enabled=true, AttributeName=ttl_timestamp"

**Using Terraform:**

.. code-block:: hcl

    resource "aws_dynamodb_table" "actingweb_attributes" {
      name           = "${var.prefix}_attributes"
      billing_mode   = "PAY_PER_REQUEST"
      hash_key       = "id"
      range_key      = "bucket_name"

      attribute {
        name = "id"
        type = "S"
      }

      attribute {
        name = "bucket_name"
        type = "S"
      }

      ttl {
        attribute_name = "ttl_timestamp"
        enabled        = true
      }
    }

**Using CloudFormation:**

.. code-block:: yaml

    ActingWebAttributesTable:
      Type: AWS::DynamoDB::Table
      Properties:
        TableName: !Sub "${Prefix}_attributes"
        AttributeDefinitions:
          - AttributeName: id
            AttributeType: S
          - AttributeName: bucket_name
            AttributeType: S
        KeySchema:
          - AttributeName: id
            KeyType: HASH
          - AttributeName: bucket_name
            KeyType: RANGE
        BillingMode: PAY_PER_REQUEST
        TimeToLiveSpecification:
          AttributeName: ttl_timestamp
          Enabled: true

Verification
~~~~~~~~~~~~

Verify TTL is enabled on your table:

.. code-block:: bash

    aws dynamodb describe-time-to-live --table-name {your_prefix}_attributes

Expected output:

.. code-block:: json

    {
        "TimeToLiveDescription": {
            "TimeToLiveStatus": "ENABLED",
            "AttributeName": "ttl_timestamp"
        }
    }

Scheduled Cleanup Lambda
------------------------

While DynamoDB TTL handles most cleanup automatically, orphaned index entries
may remain when the primary data is deleted. Deploy a scheduled cleanup Lambda
to handle these cases.

Key Requirements
~~~~~~~~~~~~~~~~

- Deploy as a **separate Lambda function** from your serving Lambdas
- Trigger via EventBridge/CloudWatch Events on a schedule (e.g., daily)
- Do NOT call cleanup methods from your request handling code
- Set appropriate timeout (5 minutes recommended)

Cleanup Handler Example
~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    """
    cleanup_handler.py - Database maintenance Lambda

    Deploy as a separate Lambda from your serving function.
    Triggered by EventBridge on a schedule (daily recommended).
    """

    import logging
    from actingweb.config import Config
    from actingweb.oauth_session import OAuth2SessionManager
    from actingweb.oauth2_server.token_manager import ActingWebTokenManager

    logger = logging.getLogger(__name__)


    def handler(event, context):
        """
        Clean up expired tokens and orphaned index entries.

        Returns:
            dict: Cleanup results
        """
        # Initialize with your application's config
        config = Config(
            database="dynamodb",
            # ... your config settings ...
        )

        results = {}

        # Clean up OAuth sessions
        session_mgr = OAuth2SessionManager(config)
        results["oauth_sessions"] = session_mgr.clear_expired_sessions()

        # Clean up SPA tokens
        results["spa_tokens"] = session_mgr.cleanup_expired_tokens()

        # Clean up MCP tokens and indexes
        token_mgr = ActingWebTokenManager(config)
        results["mcp_tokens"] = token_mgr.cleanup_expired_tokens()

        logger.info(f"Cleanup complete: {results}")

        return {
            "statusCode": 200,
            "body": results
        }

Serverless Framework Deployment
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: yaml

    # serverless.yml
    functions:
      cleanup:
        handler: cleanup_handler.handler
        timeout: 300  # 5 minutes
        memorySize: 256
        events:
          - schedule:
              rate: cron(0 3 * * ? *)  # Daily at 03:00 UTC
              enabled: true
        environment:
          AWS_DB_PREFIX: ${self:custom.dbPrefix}

AWS SAM Template
~~~~~~~~~~~~~~~~

.. code-block:: yaml

    # template.yaml
    CleanupFunction:
      Type: AWS::Serverless::Function
      Properties:
        Handler: cleanup_handler.handler
        Runtime: python3.11
        Timeout: 300
        MemorySize: 256
        Events:
          DailyCleanup:
            Type: Schedule
            Properties:
              Schedule: cron(0 3 * * ? *)
              Enabled: true

Required IAM Permissions
~~~~~~~~~~~~~~~~~~~~~~~~

The cleanup Lambda needs these DynamoDB permissions:

.. code-block:: yaml

    # IAM policy for cleanup Lambda
    - Effect: Allow
      Action:
        - dynamodb:Query
        - dynamodb:GetItem
        - dynamodb:DeleteItem
      Resource:
        - !GetAtt ActingWebAttributesTable.Arn

**Recommended Schedule:** Daily at low-traffic time (e.g., 03:00 UTC)

Monitoring
----------

Set up CloudWatch alarms to detect issues:

Table Size Monitoring
~~~~~~~~~~~~~~~~~~~~~

Alert if the attributes table item count grows beyond expected threshold
(indicates TTL may not be working):

.. code-block:: yaml

    # CloudWatch alarm for table size
    TableSizeAlarm:
      Type: AWS::CloudWatch::Alarm
      Properties:
        AlarmName: ActingWeb-AttributeTableSize
        MetricName: ItemCount
        Namespace: AWS/DynamoDB
        Statistic: Average
        Period: 86400  # 24 hours
        EvaluationPeriods: 1
        Threshold: 100000  # Adjust based on your expected volume
        ComparisonOperator: GreaterThanThreshold
        Dimensions:
          - Name: TableName
            Value: !Ref ActingWebAttributesTable

Cleanup Lambda Monitoring
~~~~~~~~~~~~~~~~~~~~~~~~~

Alert if the cleanup Lambda fails:

.. code-block:: yaml

    CleanupErrorAlarm:
      Type: AWS::CloudWatch::Alarm
      Properties:
        AlarmName: ActingWeb-CleanupLambdaErrors
        MetricName: Errors
        Namespace: AWS/Lambda
        Statistic: Sum
        Period: 3600
        EvaluationPeriods: 1
        Threshold: 1
        ComparisonOperator: GreaterThanOrEqualToThreshold
        Dimensions:
          - Name: FunctionName
            Value: !Ref CleanupFunction

TTL Deletion Monitoring
~~~~~~~~~~~~~~~~~~~~~~~

Monitor DynamoDB's ``TimeToLiveDeletedItemCount`` metric to verify TTL is
actively cleaning up data:

.. code-block:: bash

    aws cloudwatch get-metric-statistics \
      --namespace AWS/DynamoDB \
      --metric-name TimeToLiveDeletedItemCount \
      --dimensions Name=TableName,Value={your_prefix}_attributes \
      --start-time $(date -u -d '7 days ago' +%Y-%m-%dT%H:%M:%SZ) \
      --end-time $(date -u +%Y-%m-%dT%H:%M:%SZ) \
      --period 86400 \
      --statistics Sum

Data Lifecycle Reference
------------------------

The following table shows TTL values for different data types:

.. list-table:: Data Lifecycle Reference
   :widths: 25 15 60
   :header-rows: 1

   * - Data Type
     - TTL
     - Notes
   * - OAuth sessions
     - 10 minutes
     - Postponed actor creation flow
   * - SPA access tokens
     - 1 hour
     - Web app authentication
   * - SPA refresh tokens
     - 2 weeks
     - Web app token refresh
   * - MCP auth codes
     - 10 minutes
     - OAuth2 authorization flow
   * - MCP access tokens
     - 1 hour
     - MCP client authentication
   * - MCP refresh tokens
     - 30 days
     - MCP client token refresh
   * - Index entries
     - +2 hours
     - Buffer over data TTL

These values are defined in ``actingweb/constants.py``:

.. code-block:: python

    # OAuth session TTL (for postponed actor creation)
    OAUTH_SESSION_TTL = 600  # 10 minutes

    # SPA token TTLs
    SPA_ACCESS_TOKEN_TTL = 3600  # 1 hour
    SPA_REFRESH_TOKEN_TTL = 86400 * 14  # 2 weeks

    # MCP token TTLs
    MCP_AUTH_CODE_TTL = 600  # 10 minutes
    MCP_ACCESS_TOKEN_TTL = 3600  # 1 hour
    MCP_REFRESH_TOKEN_TTL = 2592000  # 30 days

    # Index buffer
    INDEX_TTL_BUFFER = 7200  # 2 hours

Rollout Guide
-------------

When deploying TTL support to an existing application:

1. **Update Library**: Upgrade to ActingWeb version with TTL support

2. **Deploy Code First**: Deploy your application code
   - TTL timestamps are stored but DynamoDB doesn't act on them yet
   - This is a safe, non-breaking change

3. **Enable DynamoDB TTL**: Apply the TTL configuration
   - Run the AWS CLI command or apply Terraform/CloudFormation
   - DynamoDB begins background cleanup

4. **Deploy Cleanup Lambda**: Deploy the scheduled cleanup Lambda
   - Handles orphaned index entries
   - Run immediately after deployment to clean existing data

5. **Enable Monitoring**: Set up CloudWatch alarms
   - Table size monitoring
   - Cleanup Lambda error alerts
   - TTL deletion metrics

See Also
--------

- :doc:`../sdk/attributes-buckets` - Attribute storage system details
- :doc:`../quickstart/deployment` - General deployment guide
- :doc:`authentication` - Authentication configuration
