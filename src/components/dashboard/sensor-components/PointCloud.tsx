'use client';

import React from 'react';
import PointCloudViewer from './PointCloudViewer';

interface PointCloudProps {
  robotId: number;
}

const PointCloud: React.FC<PointCloudProps> = ({ robotId }) => {
  return <PointCloudViewer topic="/scan/points" robotId={robotId} />;
};

export default PointCloud;